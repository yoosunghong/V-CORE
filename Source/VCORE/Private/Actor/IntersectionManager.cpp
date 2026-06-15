#include "IntersectionManager.h"

#include "AGVActor.h"

AIntersectionManager::AIntersectionManager()
{
    PrimaryActorTick.bCanEverTick = false;
}

void AIntersectionManager::Configure(float InEntryDistanceRatio, float InExitDistanceRatio, const FString& InSectionId)
{
    EntryDistanceRatio = InEntryDistanceRatio;
    ExitDistanceRatio = InExitDistanceRatio;
    SectionId = InSectionId;
}

bool AIntersectionManager::RequestEntry(AAGVActor* Agv, double SimTimestampSeconds)
{
    if (!IsValid(Agv))
    {
        return false;
    }

    if (ActiveAgv == Agv)
    {
        return true;
    }

    if (!Queue.Contains(Agv))
    {
        Queue.Add(Agv);
        WaitStartedAt.Add(Agv, SimTimestampSeconds);
    }

    if (ActiveAgv == nullptr && Queue.Num() > 0 && Queue[0] == Agv)
    {
        ActiveAgv = Agv;

        if (const double* WaitStarted = WaitStartedAt.Find(Agv))
        {
            TotalWaitSeconds += FMath::Max(0.0, SimTimestampSeconds - *WaitStarted);
            ++WaitSamples;
        }

        WaitStartedAt.Remove(Agv);
        Queue.RemoveSingle(Agv);
        return true;
    }

    return false;
}

void AIntersectionManager::ReleaseEntry(AAGVActor* Agv, double SimTimestampSeconds)
{
    if (!IsValid(Agv))
    {
        return;
    }

    if (ActiveAgv == Agv)
    {
        ActiveAgv = nullptr;
    }

    if (WaitStartedAt.Contains(Agv))
    {
        TotalWaitSeconds += FMath::Max(0.0, SimTimestampSeconds - WaitStartedAt[Agv]);
        ++WaitSamples;
        WaitStartedAt.Remove(Agv);
    }

    Queue.RemoveSingle(Agv);
}

bool AIntersectionManager::IsWithinIntersection(float DistanceAlongPath, float PathLength) const
{
    const float SafePathLength = FMath::Max(PathLength, 1.0f);
    const float DistanceRatio = FMath::Fmod(DistanceAlongPath + SafePathLength, SafePathLength) / SafePathLength;
    return DistanceRatio >= EntryDistanceRatio && DistanceRatio <= ExitDistanceRatio;
}

double AIntersectionManager::GetWaitDuration(AAGVActor* Agv, double SimTimestampSeconds) const
{
    if (const double* WaitStarted = WaitStartedAt.Find(Agv))
    {
        return FMath::Max(0.0, SimTimestampSeconds - *WaitStarted);
    }

    return 0.0;
}

TArray<FString> AIntersectionManager::GetQueuedAgvIds() const
{
    TArray<FString> Result;
    for (const AAGVActor* Agv : Queue)
    {
        if (IsValid(Agv))
        {
            Result.Add(Agv->GetAgvId());
        }
    }
    return Result;
}

double AIntersectionManager::GetAverageWaitTimeSeconds() const
{
    return WaitSamples > 0 ? TotalWaitSeconds / static_cast<double>(WaitSamples) : 0.0;
}

void AIntersectionManager::ResetForRun()
{
    Queue.Reset();
    WaitStartedAt.Reset();
    ActiveAgv = nullptr;
    TotalWaitSeconds = 0.0;
    WaitSamples = 0;
}
