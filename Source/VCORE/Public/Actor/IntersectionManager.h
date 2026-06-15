#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "IntersectionManager.generated.h"

class AAGVActor;

UCLASS()
class VCORE_API AIntersectionManager : public AActor
{
    GENERATED_BODY()

public:
    AIntersectionManager();

    void Configure(float InEntryDistanceRatio, float InExitDistanceRatio, const FString& InSectionId);
    bool RequestEntry(AAGVActor* Agv, double SimTimestampSeconds);
    void ReleaseEntry(AAGVActor* Agv, double SimTimestampSeconds);
    bool IsWithinIntersection(float DistanceAlongPath, float PathLength) const;
    double GetWaitDuration(AAGVActor* Agv, double SimTimestampSeconds) const;
    TArray<FString> GetQueuedAgvIds() const;
    double GetAverageWaitTimeSeconds() const;
    void ResetForRun();
    FString GetSectionId() const { return SectionId; }

private:
    float EntryDistanceRatio = 0.42f;
    float ExitDistanceRatio = 0.58f;
    FString SectionId = TEXT("INTERSECTION_X");

    TArray<TObjectPtr<AAGVActor>> Queue;
    TMap<TObjectPtr<AAGVActor>, double> WaitStartedAt;
    TObjectPtr<AAGVActor> ActiveAgv = nullptr;

    double TotalWaitSeconds = 0.0;
    int32 WaitSamples = 0;
};
