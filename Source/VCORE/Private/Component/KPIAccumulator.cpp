#include "KPIAccumulator.h"

#include "AGVActor.h"
#include "IntersectionManager.h"
#include "TrafficManagerActor.h"
#include "Dom/JsonObject.h"
#include "Math/UnrealMathUtility.h"

void UKPIAccumulator::Reset()
{
    TotalTasksCompleted = 0;
    CollisionEvents = 0;
}

int32 UKPIAccumulator::RecordTaskCompleted()
{
    return ++TotalTasksCompleted;
}

int32 UKPIAccumulator::RecordCollision()
{
    return ++CollisionEvents;
}

TSharedPtr<FJsonObject> UKPIAccumulator::BuildRuntimeKpis(
    double SimDurationSeconds,
    const TArray<TObjectPtr<AAGVActor>>& Agvs,
    const AIntersectionManager* IntersectionManager,
    const ATrafficManagerActor* TrafficManager) const
{
    const double Hours = SimHours(SimDurationSeconds);
    TSharedPtr<FJsonObject> KpiJson = MakeShared<FJsonObject>();
    KpiJson->SetNumberField(TEXT("throughput"), TotalTasksCompleted / Hours);
    KpiJson->SetNumberField(TEXT("avg_wait_time"), AverageWaitSeconds(IntersectionManager, TrafficManager));
    KpiJson->SetNumberField(TEXT("collision_risk"), CollisionEvents / Hours);
    KpiJson->SetNumberField(TEXT("uptime"), AverageUptime(SimDurationSeconds, Agvs));
    return KpiJson;
}

FProcessKpiSnapshot UKPIAccumulator::BuildScenarioSnapshot(
    double SimDurationSeconds,
    int32 ActiveAgvCount,
    const TArray<TObjectPtr<AAGVActor>>& Agvs,
    const AIntersectionManager* IntersectionManager,
    const ATrafficManagerActor* TrafficManager) const
{
    const double Hours = SimHours(SimDurationSeconds);
    FProcessKpiSnapshot Snapshot;
    Snapshot.Throughput = static_cast<float>(TotalTasksCompleted / Hours);
    Snapshot.AvgWaitSec = static_cast<float>(AverageWaitSeconds(IntersectionManager, TrafficManager));
    Snapshot.CollisionCount = CollisionEvents;
    Snapshot.UptimeRatio = static_cast<float>(AverageUptime(SimDurationSeconds, Agvs));
    Snapshot.ActiveAgvs = ActiveAgvCount;
    return Snapshot;
}

void UKPIAccumulator::WriteStatusFields(
    FJsonObject& Json,
    double SimTimestampSeconds,
    bool bSimRunning,
    bool bSimPaused,
    const AIntersectionManager* IntersectionManager,
    const ATrafficManagerActor* TrafficManager) const
{
    const double Hours = SimHours(SimTimestampSeconds);
    Json.SetNumberField(TEXT("throughput"), TotalTasksCompleted / Hours);
    Json.SetNumberField(TEXT("avg_wait_time"), AverageWaitSeconds(IntersectionManager, TrafficManager));
    Json.SetNumberField(TEXT("collision_risk"), CollisionEvents / Hours);
    Json.SetNumberField(TEXT("uptime"), bSimRunning ? (bSimPaused ? 0.0 : 1.0) : 0.0);
}

double UKPIAccumulator::AverageWaitSeconds(
    const AIntersectionManager* IntersectionManager,
    const ATrafficManagerActor* TrafficManager)
{
    if (TrafficManager)
    {
        return TrafficManager->GetAverageWaitTimeSeconds();
    }

    return IntersectionManager ? IntersectionManager->GetAverageWaitTimeSeconds() : 0.0;
}

double UKPIAccumulator::SimHours(double SimDurationSeconds)
{
    return FMath::Max(SimDurationSeconds / 3600.0, 1.0 / 3600.0);
}

double UKPIAccumulator::AverageUptime(double SimDurationSeconds, const TArray<TObjectPtr<AAGVActor>>& Agvs)
{
    const double SafeSimDuration = FMath::Max(SimDurationSeconds, 1.0);
    double TotalActiveTime = 0.0;
    int32 ValidAgvCount = 0;
    for (const AAGVActor* Agv : Agvs)
    {
        if (IsValid(Agv))
        {
            TotalActiveTime += Agv->GetActiveTimeSeconds();
            ++ValidAgvCount;
        }
    }

    const double Uptime = ValidAgvCount > 0 ? TotalActiveTime / (SafeSimDuration * ValidAgvCount) : 0.0;
    return FMath::Clamp(Uptime, 0.0, 1.0);
}
