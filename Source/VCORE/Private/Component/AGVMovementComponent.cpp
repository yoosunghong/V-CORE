#include "AGVMovementComponent.h"

#include "AGVActor.h"
#include "AGVPathActor.h"
#include "AGVSimController.h"
#include "IntersectionManager.h"
#include "SimEventBus.h"
#include "StationActor.h"
#include "TrafficManagerActor.h"
#include "Components/SplineComponent.h"

UAGVMovementComponent::UAGVMovementComponent()
{
    PrimaryComponentTick.bCanEverTick = false;
}

void UAGVMovementComponent::Configure(
    AAGVSimController* InController,
    AIntersectionManager* InIntersectionManager,
    ATrafficManagerActor* InTrafficManager,
    AAGVPathActor* InPathActor,
    float InInitialDistance,
    float InSimSpeed,
    float InBottleneckThresholdSec)
{
    Controller = InController;
    IntersectionManager = InIntersectionManager;
    TrafficManager = InTrafficManager;
    PathActor = InPathActor;
    InitialDistance = InInitialDistance;
    DistanceAlongPath = InInitialDistance;
    LastDistanceBeforeMove = InInitialDistance;
    SimSpeedMultiplier = FMath::Max(InSimSpeed, 1.0f);
    BottleneckThresholdSec = InBottleneckThresholdSec;
    BatteryPercent = 100.0f;
    bApproachActive = true;
    ResetRouteReservationState();
    // No snap onto the spline here — the AGV stays at its placed position and drives to the path
    // entry in TickApproach once it starts moving.
}

void UAGVMovementComponent::StartRun()
{
    DistanceAlongPath = InitialDistance;
    LastDistanceBeforeMove = InitialDistance;
    CurrentSpeed = 0.0f;
    bApproachActive = true;
    ResetRouteReservationState();
}

void UAGVMovementComponent::StopMovement()
{
    CurrentSpeed = 0.0f;
}

void UAGVMovementComponent::ResetForOffline()
{
    DistanceAlongPath = InitialDistance;
    LastDistanceBeforeMove = InitialDistance;
    StationTargetDistance = 0.0f;
    CurrentSpeed = 0.0f;
    BatteryPercent = 100.0f;
    bApproachActive = false;
    ResetRouteReservationState();
}

void UAGVMovementComponent::TickMovement(float DeltaSeconds, EAGVState CurrentState, const FString& AgvId)
{
    if (CurrentState != EAGVState::MovingToPickup && CurrentState != EAGVState::MovingToDropoff
        && CurrentState != EAGVState::WaitingAtSection && CurrentState != EAGVState::MovingToStation)
    {
        CurrentSpeed = 0.0f;
        return;
    }

    if (!GetPathSpline())
    {
        CurrentSpeed = 0.0f;
        return;
    }

    AAGVActor* OwnerAgv = Cast<AAGVActor>(GetOwner());
    if (!OwnerAgv)
    {
        CurrentSpeed = 0.0f;
        return;
    }

    // Drive to the assigned path first; only follow the spline once we're on it.
    if (bApproachActive)
    {
        TickApproach(DeltaSeconds, OwnerAgv);
        return;
    }

    const float PathLength = GetPathLength();
    const float MoveDistance = BaseMoveSpeed * SimSpeedMultiplier * DeltaSeconds;
    const float NextDistance = DistanceAlongPath + MoveDistance;
    const double SimTimestamp = Controller ? Controller->GetSimTimestampSeconds() : 0.0;

    if (ShouldRequestTrafficSegment(NextDistance))
    {
        const FString SegmentId = ActiveRouteSegmentId.IsEmpty() ? TEXT("INTERSECTION_X") : ActiveRouteSegmentId;
        const bool bReservationGranted = TrafficManager
            ? TrafficManager->RequestReservation(OwnerAgv, SegmentId, SimTimestamp)
            : (IntersectionManager && IntersectionManager->RequestEntry(OwnerAgv, SimTimestamp));

        if (!bReservationGranted)
        {
            if (!bWaitingForIntersection)
            {
                ResumeStateAfterWait = (CurrentState == EAGVState::WaitingAtSection) ? ResumeStateAfterWait : CurrentState;
                OwnerAgv->TransitionTo(EAGVState::WaitingAtSection);
                bWaitingForIntersection = true;
            }

            const double WaitDuration = TrafficManager
                ? TrafficManager->GetWaitDuration(OwnerAgv, SegmentId, SimTimestamp)
                : (IntersectionManager ? IntersectionManager->GetWaitDuration(OwnerAgv, SimTimestamp) : 0.0);
            if (!bBottleneckEventEmitted && WaitDuration >= BottleneckThresholdSec && Controller)
            {
                bBottleneckEventEmitted = true;
                if (USimEventBus* Bus = USimEventBus::Get(this))
                {
                    FSimBottleneckEvent BottleneckEvent;
                    BottleneckEvent.AgvId = AgvId;
                    BottleneckEvent.SectionId = SegmentId;
                    BottleneckEvent.WaitDurationSec = WaitDuration;
                    BottleneckEvent.QueuedAgvIds = TrafficManager
                        ? TrafficManager->GetQueuedAgvIds(SegmentId)
                        : (IntersectionManager ? IntersectionManager->GetQueuedAgvIds() : TArray<FString>());
                    Bus->BroadcastBottleneck(BottleneckEvent);
                }
            }

            CurrentSpeed = 0.0f;
            return;
        }

        bWaitingForIntersection = false;
        bBottleneckEventEmitted = false;
        bInsideIntersection = true;
        if (CurrentState == EAGVState::WaitingAtSection)
        {
            OwnerAgv->TransitionTo(ResumeStateAfterWait);
        }
    }

    LastDistanceBeforeMove = DistanceAlongPath;
    DistanceAlongPath = FMath::Fmod(NextDistance + PathLength, PathLength);
    CurrentSpeed = BaseMoveSpeed * SimSpeedMultiplier;
    BatteryPercent = FMath::Max(20.0f, BatteryPercent - DeltaSeconds * 0.15f);
    UpdateTransformFromDistance();
    OwnerAgv->HandleCheckpointTransitions();

    if (bInsideIntersection && !ShouldRequestTrafficSegment(DistanceAlongPath))
    {
        const FString SegmentId = ActiveRouteSegmentId.IsEmpty() ? TEXT("INTERSECTION_X") : ActiveRouteSegmentId;
        if (TrafficManager)
        {
            TrafficManager->ReleaseReservation(OwnerAgv, SegmentId, SimTimestamp);
        }
        else if (IntersectionManager)
        {
            IntersectionManager->ReleaseEntry(OwnerAgv, SimTimestamp);
        }
        bInsideIntersection = false;
    }
}

void UAGVMovementComponent::TickApproach(float DeltaSeconds, AAGVActor* OwnerAgv)
{
    USplineComponent* PathSpline = GetPathSpline();
    if (!PathSpline)
    {
        bApproachActive = false;
        CurrentSpeed = 0.0f;
        return;
    }

    const float PathLength = GetPathLength();
    const float EntryDistance = FMath::Fmod(InitialDistance + PathLength, PathLength);
    const FVector EntryLocation = PathSpline->GetLocationAtDistanceAlongSpline(EntryDistance, ESplineCoordinateSpace::World);
    const FVector CurrentLocation = OwnerAgv->GetActorLocation();
    const FVector ToEntry = EntryLocation - CurrentLocation;
    const float Remaining = static_cast<float>(ToEntry.Size());
    const float Step = BaseMoveSpeed * SimSpeedMultiplier * DeltaSeconds;

    CurrentSpeed = BaseMoveSpeed * SimSpeedMultiplier;
    BatteryPercent = FMath::Max(20.0f, BatteryPercent - DeltaSeconds * 0.15f);

    constexpr float ApproachArrivalRadius = 50.0f;
    if (Remaining <= FMath::Max(Step, ApproachArrivalRadius))
    {
        // Reached the path — lock onto the spline and hand off to the follower next tick.
        bApproachActive = false;
        DistanceAlongPath = EntryDistance;
        LastDistanceBeforeMove = EntryDistance;
        UpdateTransformFromDistance();
        return;
    }

    const FVector NewLocation = CurrentLocation + (ToEntry / Remaining) * Step;
    OwnerAgv->SetActorLocation(NewLocation);
    OwnerAgv->SetActorRotation(ToEntry.Rotation());
}

void UAGVMovementComponent::UpdateTransformFromDistance()
{
    USplineComponent* PathSpline = GetPathSpline();
    if (!PathSpline)
    {
        return;
    }

    const float PathLength = GetPathLength();
    const float WrappedDistance = FMath::Fmod(DistanceAlongPath + PathLength, PathLength);
    if (AActor* Owner = GetOwner())
    {
        Owner->SetActorLocation(PathSpline->GetLocationAtDistanceAlongSpline(WrappedDistance, ESplineCoordinateSpace::World));
        Owner->SetActorRotation(PathSpline->GetRotationAtDistanceAlongSpline(WrappedDistance, ESplineCoordinateSpace::World));
    }
}

float UAGVMovementComponent::FindDistanceClosestToWorldLocation(const FVector& WorldLocation) const
{
    USplineComponent* PathSpline = GetPathSpline();
    if (!PathSpline)
    {
        return DistanceAlongPath;
    }

    const float PathLength = GetPathLength();
    float BestDistance = 0.0f;
    float BestDistanceSquared = TNumericLimits<float>::Max();
    constexpr int32 SampleCount = 96;
    for (int32 Index = 0; Index <= SampleCount; ++Index)
    {
        const float CandidateDistance = PathLength * (static_cast<float>(Index) / static_cast<float>(SampleCount));
        const FVector CandidateLocation = PathSpline->GetLocationAtDistanceAlongSpline(CandidateDistance, ESplineCoordinateSpace::World);
        const float DistanceSquared = FVector::DistSquared(CandidateLocation, WorldLocation);
        if (DistanceSquared < BestDistanceSquared)
        {
            BestDistanceSquared = DistanceSquared;
            BestDistance = CandidateDistance;
        }
    }

    return BestDistance;
}

float UAGVMovementComponent::EstimateTravelDistanceToStation(const AStationActor* Station) const
{
    if (!IsValid(Station))
    {
        return 0.0f;
    }

    const float TargetDistance = FindDistanceClosestToWorldLocation(Station->GetDockingTransform().GetLocation());
    const float PathLength = GetPathLength();
    return FMath::Fmod(TargetDistance - DistanceAlongPath + PathLength, PathLength);
}

float UAGVMovementComponent::EstimateEtaToStation(const AStationActor* Station) const
{
    const float EffectiveSpeed = FMath::Max(BaseMoveSpeed * SimSpeedMultiplier, 1.0f);
    return EstimateTravelDistanceToStation(Station) / EffectiveSpeed;
}

FString UAGVMovementComponent::GetCurrentRouteSegmentId() const
{
    const AAGVActor* OwnerAgv = Cast<AAGVActor>(GetOwner());
    if (TrafficManager && OwnerAgv)
    {
        const FRouteReservationSnapshot Snapshot = TrafficManager->GetReservationSnapshotForAgv(OwnerAgv);
        if (!Snapshot.SegmentId.IsEmpty())
        {
            return Snapshot.SegmentId;
        }
    }

    return ActiveRouteSegmentId;
}

FString UAGVMovementComponent::GetReservationState(EAGVState CurrentState) const
{
    const AAGVActor* OwnerAgv = Cast<AAGVActor>(GetOwner());
    if (TrafficManager && OwnerAgv)
    {
        return TrafficManager->GetReservationSnapshotForAgv(OwnerAgv).ReservationState;
    }

    return CurrentState == EAGVState::WaitingAtSection ? TEXT("waiting") : TEXT("unreserved");
}

double UAGVMovementComponent::GetRouteWaitDurationSeconds() const
{
    const AAGVActor* OwnerAgv = Cast<AAGVActor>(GetOwner());
    if (TrafficManager && OwnerAgv)
    {
        return TrafficManager->GetReservationSnapshotForAgv(OwnerAgv).WaitDurationSec;
    }

    return 0.0;
}

USplineComponent* UAGVMovementComponent::GetPathSpline() const
{
    return IsValid(PathActor) ? PathActor->GetPathSpline() : nullptr;
}

float UAGVMovementComponent::GetPathLength() const
{
    const USplineComponent* PathSpline = GetPathSpline();
    return PathSpline ? FMath::Max(PathSpline->GetSplineLength(), 1.0f) : 1.0f;
}

bool UAGVMovementComponent::WasLastMoveAcrossDistance(float TargetDistance) const
{
    if (LastDistanceBeforeMove <= DistanceAlongPath)
    {
        return LastDistanceBeforeMove < TargetDistance && DistanceAlongPath >= TargetDistance;
    }

    return TargetDistance >= LastDistanceBeforeMove || TargetDistance <= DistanceAlongPath;
}

void UAGVMovementComponent::ResetRouteReservationState()
{
    bWaitingForIntersection = false;
    bBottleneckEventEmitted = false;
    bInsideIntersection = false;
    ActiveRouteSegmentId = TrafficManager ? TrafficManager->GetDefaultIntersectionSegmentId() : TEXT("INTERSECTION_X");
    ResumeStateAfterWait = EAGVState::MovingToPickup;
}

void UAGVMovementComponent::ClearManagers()
{
    IntersectionManager = nullptr;
    TrafficManager = nullptr;
    ActiveRouteSegmentId.Reset();
}

bool UAGVMovementComponent::ShouldRequestTrafficSegment(float NextDistance) const
{
    if (bInsideIntersection)
    {
        return false;
    }

    const FString SegmentId = ActiveRouteSegmentId.IsEmpty() ? TEXT("INTERSECTION_X") : ActiveRouteSegmentId;
    if (TrafficManager)
    {
        return TrafficManager->IsWithinSegment(SegmentId, NextDistance, GetPathLength());
    }

    return IntersectionManager && IntersectionManager->IsWithinIntersection(NextDistance, GetPathLength());
}
