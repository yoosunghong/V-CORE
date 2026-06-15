#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "TrafficManagerActor.generated.h"

class AAGVActor;

USTRUCT(BlueprintType)
struct FRouteReservationSnapshot
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Traffic")
    FString SegmentId;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Traffic")
    FString ReservationState = TEXT("unreserved");

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Traffic")
    FString ReservedByAgvId;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Traffic")
    double WaitDurationSec = 0.0;
};

UCLASS()
class VCORE_API ATrafficManagerActor : public AActor
{
    GENERATED_BODY()

public:
    ATrafficManagerActor();

    void ConfigureDefaultIntersection(float InEntryDistanceRatio, float InExitDistanceRatio, const FString& InSegmentId);
    void ResetForRun();

    bool RequestReservation(AAGVActor* Agv, const FString& SegmentId, double SimTimestampSeconds);
    void ReleaseReservation(AAGVActor* Agv, const FString& SegmentId, double SimTimestampSeconds);
    bool IsWithinSegment(const FString& SegmentId, float DistanceAlongPath, float PathLength) const;
    bool CanReserveSegmentFor(const AAGVActor* Agv, const FString& SegmentId) const;

    double GetWaitDuration(AAGVActor* Agv, const FString& SegmentId, double SimTimestampSeconds) const;
    TArray<FString> GetQueuedAgvIds(const FString& SegmentId) const;
    FRouteReservationSnapshot GetReservationSnapshotForAgv(const AAGVActor* Agv) const;
    FString GetDefaultIntersectionSegmentId() const { return DefaultIntersectionSegmentId; }
    int32 GetBlockedSegmentCount() const;
    double GetAverageWaitTimeSeconds() const;

private:
    struct FTrafficSegment
    {
        float EntryDistanceRatio = 0.42f;
        float ExitDistanceRatio = 0.58f;
        FString SegmentId = TEXT("INTERSECTION_X");
        TArray<TWeakObjectPtr<AAGVActor>> Queue;
        TMap<TWeakObjectPtr<AAGVActor>, double> WaitStartedAt;
        TWeakObjectPtr<AAGVActor> ActiveAgv;
    };

    FTrafficSegment& FindOrAddSegment(const FString& SegmentId);
    const FTrafficSegment* FindSegment(const FString& SegmentId) const;

    UPROPERTY(EditAnywhere, Category="VCORE|Traffic")
    FString DefaultIntersectionSegmentId = TEXT("INTERSECTION_X");

    TMap<FString, FTrafficSegment> Segments;
    double TotalWaitSeconds = 0.0;
    int32 WaitSamples = 0;
};
