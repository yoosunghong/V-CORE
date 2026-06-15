#include "TrafficManagerActor.h"

#include "AGVActor.h"

ATrafficManagerActor::ATrafficManagerActor()
{
    PrimaryActorTick.bCanEverTick = false;
}

void ATrafficManagerActor::ConfigureDefaultIntersection(float InEntryDistanceRatio, float InExitDistanceRatio, const FString& InSegmentId)
{
    DefaultIntersectionSegmentId = InSegmentId.IsEmpty() ? TEXT("INTERSECTION_X") : InSegmentId;
    FTrafficSegment& Segment = FindOrAddSegment(DefaultIntersectionSegmentId);
    Segment.EntryDistanceRatio = InEntryDistanceRatio;
    Segment.ExitDistanceRatio = InExitDistanceRatio;
    Segment.SegmentId = DefaultIntersectionSegmentId;
}

void ATrafficManagerActor::ResetForRun()
{
    for (TPair<FString, FTrafficSegment>& Pair : Segments)
    {
        Pair.Value.Queue.Reset();
        Pair.Value.WaitStartedAt.Reset();
        Pair.Value.ActiveAgv.Reset();
    }

    TotalWaitSeconds = 0.0;
    WaitSamples = 0;
}

bool ATrafficManagerActor::RequestReservation(AAGVActor* Agv, const FString& SegmentId, double SimTimestampSeconds)
{
    if (!IsValid(Agv))
    {
        return false;
    }

    FTrafficSegment& Segment = FindOrAddSegment(SegmentId);
    TWeakObjectPtr<AAGVActor> AgvKey(Agv);
    if (Segment.ActiveAgv.Get() == Agv)
    {
        return true;
    }

    if (!Segment.Queue.Contains(AgvKey))
    {
        Segment.Queue.Add(AgvKey);
        Segment.WaitStartedAt.Add(AgvKey, SimTimestampSeconds);
    }

    if (!Segment.ActiveAgv.IsValid() && Segment.Queue.Num() > 0 && Segment.Queue[0].Get() == Agv)
    {
        Segment.ActiveAgv = Agv;

        if (const double* WaitStarted = Segment.WaitStartedAt.Find(AgvKey))
        {
            TotalWaitSeconds += FMath::Max(0.0, SimTimestampSeconds - *WaitStarted);
            ++WaitSamples;
        }

        Segment.WaitStartedAt.Remove(AgvKey);
        Segment.Queue.RemoveSingle(AgvKey);
        return true;
    }

    return false;
}

void ATrafficManagerActor::ReleaseReservation(AAGVActor* Agv, const FString& SegmentId, double SimTimestampSeconds)
{
    if (!IsValid(Agv))
    {
        return;
    }

    FTrafficSegment& Segment = FindOrAddSegment(SegmentId);
    TWeakObjectPtr<AAGVActor> AgvKey(Agv);
    if (Segment.ActiveAgv.Get() == Agv)
    {
        Segment.ActiveAgv.Reset();
    }

    if (const double* WaitStarted = Segment.WaitStartedAt.Find(AgvKey))
    {
        TotalWaitSeconds += FMath::Max(0.0, SimTimestampSeconds - *WaitStarted);
        ++WaitSamples;
        Segment.WaitStartedAt.Remove(AgvKey);
    }

    Segment.Queue.RemoveSingle(AgvKey);
}

bool ATrafficManagerActor::IsWithinSegment(const FString& SegmentId, float DistanceAlongPath, float PathLength) const
{
    const FTrafficSegment* Segment = FindSegment(SegmentId);
    if (!Segment)
    {
        return false;
    }

    const float SafePathLength = FMath::Max(PathLength, 1.0f);
    const float DistanceRatio = FMath::Fmod(DistanceAlongPath + SafePathLength, SafePathLength) / SafePathLength;
    return DistanceRatio >= Segment->EntryDistanceRatio && DistanceRatio <= Segment->ExitDistanceRatio;
}

bool ATrafficManagerActor::CanReserveSegmentFor(const AAGVActor* Agv, const FString& SegmentId) const
{
    const FTrafficSegment* Segment = FindSegment(SegmentId);
    if (!Segment || !IsValid(Agv))
    {
        return true;
    }

    return !Segment->ActiveAgv.IsValid() || Segment->ActiveAgv.Get() == Agv;
}

double ATrafficManagerActor::GetWaitDuration(AAGVActor* Agv, const FString& SegmentId, double SimTimestampSeconds) const
{
    const FTrafficSegment* Segment = FindSegment(SegmentId);
    if (!Segment || !IsValid(Agv))
    {
        return 0.0;
    }

    const TWeakObjectPtr<AAGVActor> AgvKey(Agv);
    if (const double* WaitStarted = Segment->WaitStartedAt.Find(AgvKey))
    {
        return FMath::Max(0.0, SimTimestampSeconds - *WaitStarted);
    }

    return 0.0;
}

TArray<FString> ATrafficManagerActor::GetQueuedAgvIds(const FString& SegmentId) const
{
    TArray<FString> Result;
    const FTrafficSegment* Segment = FindSegment(SegmentId);
    if (!Segment)
    {
        return Result;
    }

    for (const TWeakObjectPtr<AAGVActor>& QueuedAgv : Segment->Queue)
    {
        if (const AAGVActor* Agv = QueuedAgv.Get())
        {
            Result.Add(Agv->GetAgvId());
        }
    }
    return Result;
}

FRouteReservationSnapshot ATrafficManagerActor::GetReservationSnapshotForAgv(const AAGVActor* Agv) const
{
    FRouteReservationSnapshot Snapshot;
    if (!IsValid(Agv))
    {
        return Snapshot;
    }

    for (const TPair<FString, FTrafficSegment>& Pair : Segments)
    {
        const FTrafficSegment& Segment = Pair.Value;
        if (Segment.ActiveAgv.Get() == Agv)
        {
            Snapshot.SegmentId = Pair.Key;
            Snapshot.ReservationState = TEXT("reserved");
            Snapshot.ReservedByAgvId = Agv->GetAgvId();
            return Snapshot;
        }

        const TWeakObjectPtr<AAGVActor> AgvKey(const_cast<AAGVActor*>(Agv));
        if (Segment.Queue.Contains(AgvKey))
        {
            Snapshot.SegmentId = Pair.Key;
            Snapshot.ReservationState = TEXT("waiting");
            Snapshot.ReservedByAgvId = Segment.ActiveAgv.IsValid() ? Segment.ActiveAgv->GetAgvId() : FString();
            if (const double* WaitStarted = Segment.WaitStartedAt.Find(AgvKey))
            {
                Snapshot.WaitDurationSec = FMath::Max(0.0, GetWorld() ? GetWorld()->GetTimeSeconds() - *WaitStarted : 0.0);
            }
            return Snapshot;
        }
    }

    Snapshot.SegmentId = DefaultIntersectionSegmentId;
    return Snapshot;
}

int32 ATrafficManagerActor::GetBlockedSegmentCount() const
{
    int32 Count = 0;
    for (const TPair<FString, FTrafficSegment>& Pair : Segments)
    {
        if (Pair.Value.ActiveAgv.IsValid() || Pair.Value.Queue.Num() > 0)
        {
            ++Count;
        }
    }
    return Count;
}

double ATrafficManagerActor::GetAverageWaitTimeSeconds() const
{
    return WaitSamples > 0 ? TotalWaitSeconds / static_cast<double>(WaitSamples) : 0.0;
}

ATrafficManagerActor::FTrafficSegment& ATrafficManagerActor::FindOrAddSegment(const FString& SegmentId)
{
    const FString SafeSegmentId = SegmentId.IsEmpty() ? DefaultIntersectionSegmentId : SegmentId;
    FTrafficSegment& Segment = Segments.FindOrAdd(SafeSegmentId);
    Segment.SegmentId = SafeSegmentId;
    return Segment;
}

const ATrafficManagerActor::FTrafficSegment* ATrafficManagerActor::FindSegment(const FString& SegmentId) const
{
    const FString SafeSegmentId = SegmentId.IsEmpty() ? DefaultIntersectionSegmentId : SegmentId;
    return Segments.Find(SafeSegmentId);
}
