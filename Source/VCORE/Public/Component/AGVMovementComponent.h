#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "AGVTypes.h"
#include "AGVMovementComponent.generated.h"

class AAGVActor;
class AAGVPathActor;
class AAGVSimController;
class AIntersectionManager;
class AStationActor;
class ATrafficManagerActor;
class USplineComponent;

UCLASS(ClassGroup=(VCORE), BlueprintType, meta=(BlueprintSpawnableComponent))
class VCORE_API UAGVMovementComponent : public UActorComponent
{
    GENERATED_BODY()

public:
    UAGVMovementComponent();

    void Configure(
        AAGVSimController* InController,
        AIntersectionManager* InIntersectionManager,
        ATrafficManagerActor* InTrafficManager,
        AAGVPathActor* InPathActor,
        float InInitialDistance,
        float InSimSpeed,
        float InBottleneckThresholdSec);

    void StartRun();
    void StopMovement();
    void ResetForOffline();
    void TickMovement(float DeltaSeconds, EAGVState CurrentState, const FString& AgvId);
    void UpdateTransformFromDistance();

    float FindDistanceClosestToWorldLocation(const FVector& WorldLocation) const;
    float EstimateTravelDistanceToStation(const AStationActor* Station) const;
    float EstimateEtaToStation(const AStationActor* Station) const;

    FString GetCurrentRouteSegmentId() const;
    FString GetReservationState(EAGVState CurrentState) const;
    double GetRouteWaitDurationSeconds() const;

    USplineComponent* GetPathSpline() const;
    float GetPathLength() const;
    float GetDistanceAlongPath() const { return DistanceAlongPath; }
    float GetCurrentSpeed() const { return CurrentSpeed; }
    float GetBatteryPercent() const { return BatteryPercent; }
    bool WasLastMoveAcrossDistance(float TargetDistance) const;

    void SetCurrentSpeed(float InSpeed) { CurrentSpeed = InSpeed; }
    void SetBatteryPercent(float InBatteryPercent) { BatteryPercent = InBatteryPercent; }
    void SetStationTargetDistance(float InStationTargetDistance) { StationTargetDistance = InStationTargetDistance; }
    float GetStationTargetDistance() const { return StationTargetDistance; }
    void ResetRouteReservationState();
    void ClearManagers();

    UPROPERTY(EditAnywhere, Category="VCORE|AGV|Movement", meta=(ClampMin="1.0"))
    float BaseMoveSpeed = 220.0f;

private:
    bool ShouldRequestTrafficSegment(float NextDistance) const;

    // Drive the AGV in a straight line from its placed position to the entry point on its assigned
    // path (the spline location at InitialDistance). Once it reaches the path, clears bApproachActive
    // and hands off to the normal spline-follow in TickMovement. This replaces the old snap-onto-the-
    // spline teleport that dropped every AGV onto its route at run start.
    void TickApproach(float DeltaSeconds, AAGVActor* OwnerAgv);

    UPROPERTY(Transient)
    TObjectPtr<AAGVSimController> Controller = nullptr;

    UPROPERTY(Transient)
    TObjectPtr<AAGVPathActor> PathActor = nullptr;

    UPROPERTY(Transient)
    TObjectPtr<AIntersectionManager> IntersectionManager = nullptr;

    UPROPERTY(Transient)
    TObjectPtr<ATrafficManagerActor> TrafficManager = nullptr;

    float InitialDistance = 0.0f;
    float DistanceAlongPath = 0.0f;
    float LastDistanceBeforeMove = 0.0f;
    float CurrentSpeed = 0.0f;
    float SimSpeedMultiplier = 1.0f;
    float BottleneckThresholdSec = 10.0f;
    float BatteryPercent = 100.0f;
    float StationTargetDistance = 0.0f;
    bool bWaitingForIntersection = false;
    bool bBottleneckEventEmitted = false;
    bool bInsideIntersection = false;
    // True from run start until the AGV has driven onto its assigned path. While set, TickMovement
    // routes through TickApproach instead of the spline follower.
    bool bApproachActive = false;
    FString ActiveRouteSegmentId;
    EAGVState ResumeStateAfterWait = EAGVState::MovingToPickup;
};
