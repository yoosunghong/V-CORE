#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "DispatcherActor.generated.h"

class AAGVActor;
class AStationActor;
class ATrafficManagerActor;

USTRUCT(BlueprintType)
struct FDispatchScoreBreakdown
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Dispatch")
    FString AgvId;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Dispatch")
    bool bEligible = false;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Dispatch")
    float TotalScore = 0.0f;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Dispatch")
    float AvailabilityScore = 0.0f;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Dispatch")
    float DistanceScore = 0.0f;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Dispatch")
    float BatteryScore = 0.0f;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Dispatch")
    float AssignmentScore = 0.0f;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Dispatch")
    float StationScore = 0.0f;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Dispatch")
    float RouteScore = 0.0f;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Dispatch")
    float EtaSeconds = 0.0f;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Dispatch")
    FString RouteSegmentId;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Dispatch")
    FString Explanation;
};

UCLASS()
class VCORE_API ADispatcherActor : public AActor
{
    GENERATED_BODY()

public:
    ADispatcherActor();

    void Configure(ATrafficManagerActor* InTrafficManager);

    // Station-centric selection (commanded path): given a station, pick the best eligible AGV.
    AAGVActor* SelectAgvForStation(
        const TArray<TObjectPtr<AAGVActor>>& Agvs,
        AStationActor* Station,
        const FString& RequestedAgvId,
        FDispatchScoreBreakdown& OutBestScore) const;

    // AGV-centric selection (autonomous path): given an idle AGV, pick the best eligible station
    // among the candidates. Lets the dispatcher gate autonomous dispatch on station metadata.
    AStationActor* SelectStationForAgv(
        AAGVActor* Agv,
        const TArray<AStationActor*>& CandidateStations,
        FDispatchScoreBreakdown& OutBestScore) const;

    FDispatchScoreBreakdown ScoreAgvForStation(AAGVActor* Agv, AStationActor* Station, const FString& RequestedAgvId) const;

private:
    TObjectPtr<ATrafficManagerActor> TrafficManager = nullptr;
};
