#pragma once

#include "CoreMinimal.h"
#include "ScenarioVerificationComponent.h"
#include "UObject/Object.h"
#include "KPIAccumulator.generated.h"

class AAGVActor;
class AIntersectionManager;
class ATrafficManagerActor;
class FJsonObject;

/**
 * Runtime KPI accumulator for a Virtual Process simulation run.
 *
 * Owns mutable KPI counters and centralizes derived metric calculation so the controller
 * can focus on orchestration, transport, and report assembly.
 */
UCLASS(BlueprintType)
class VCORE_API UKPIAccumulator : public UObject
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintCallable, Category="VCORE|KPI")
    void Reset();

    UFUNCTION(BlueprintCallable, Category="VCORE|KPI")
    int32 RecordTaskCompleted();

    UFUNCTION(BlueprintCallable, Category="VCORE|KPI")
    int32 RecordCollision();

    UFUNCTION(BlueprintPure, Category="VCORE|KPI")
    int32 GetTotalTasksCompleted() const { return TotalTasksCompleted; }

    UFUNCTION(BlueprintPure, Category="VCORE|KPI")
    int32 GetCollisionEvents() const { return CollisionEvents; }

    TSharedPtr<FJsonObject> BuildRuntimeKpis(
        double SimDurationSeconds,
        const TArray<TObjectPtr<AAGVActor>>& Agvs,
        const AIntersectionManager* IntersectionManager,
        const ATrafficManagerActor* TrafficManager) const;

    FProcessKpiSnapshot BuildScenarioSnapshot(
        double SimDurationSeconds,
        int32 ActiveAgvCount,
        const TArray<TObjectPtr<AAGVActor>>& Agvs,
        const AIntersectionManager* IntersectionManager,
        const ATrafficManagerActor* TrafficManager) const;

    void WriteStatusFields(
        FJsonObject& Json,
        double SimTimestampSeconds,
        bool bSimRunning,
        bool bSimPaused,
        const AIntersectionManager* IntersectionManager,
        const ATrafficManagerActor* TrafficManager) const;

private:
    static double AverageWaitSeconds(
        const AIntersectionManager* IntersectionManager,
        const ATrafficManagerActor* TrafficManager);
    static double SimHours(double SimDurationSeconds);
    static double AverageUptime(double SimDurationSeconds, const TArray<TObjectPtr<AAGVActor>>& Agvs);

    UPROPERTY()
    int32 TotalTasksCompleted = 0;

    UPROPERTY()
    int32 CollisionEvents = 0;
};
