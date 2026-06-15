#include "ScenarioVerificationComponent.h"

UScenarioVerificationComponent::UScenarioVerificationComponent()
{
    PrimaryComponentTick.bCanEverTick = false;
}

void UScenarioVerificationComponent::LoadChecks(const TArray<FScenarioCheck>& Checks)
{
    ActiveChecks = Checks;
}

void UScenarioVerificationComponent::ClearChecks()
{
    ActiveChecks.Reset();
}

float UScenarioVerificationComponent::MetricValue(const FProcessKpiSnapshot& Snapshot, EScenarioMetric Metric)
{
    switch (Metric)
    {
    case EScenarioMetric::Throughput:     return Snapshot.Throughput;
    case EScenarioMetric::AvgWaitSec:     return Snapshot.AvgWaitSec;
    case EScenarioMetric::CollisionCount: return static_cast<float>(Snapshot.CollisionCount);
    case EScenarioMetric::UptimeRatio:    return Snapshot.UptimeRatio;
    case EScenarioMetric::ActiveAgvs:     return static_cast<float>(Snapshot.ActiveAgvs);
    default:                              return 0.0f;
    }
}

bool UScenarioVerificationComponent::CheckPasses(const FScenarioCheck& Check, const FProcessKpiSnapshot& Snapshot)
{
    const float Value = MetricValue(Snapshot, Check.Metric);
    switch (Check.Comparator)
    {
    case EScenarioCompare::GreaterOrEqual: return Value >= Check.Threshold - KINDA_SMALL_NUMBER;
    case EScenarioCompare::LessOrEqual:    return Value <= Check.Threshold + KINDA_SMALL_NUMBER;
    case EScenarioCompare::Equal:          return FMath::IsNearlyEqual(Value, Check.Threshold);
    default:                               return false;
    }
}

FScenarioVerdict UScenarioVerificationComponent::Evaluate(const FProcessKpiSnapshot& Snapshot) const
{
    FScenarioVerdict Verdict;
    for (const FScenarioCheck& Check : ActiveChecks)
    {
        if (CheckPasses(Check, Snapshot))
        {
            Verdict.PassedLabels.Add(Check.Label);
        }
        else
        {
            Verdict.FailedLabels.Add(Check.Label);
            Verdict.bPassed = false;
        }
    }
    return Verdict;
}

bool UScenarioVerificationComponent::HasHardViolation(const FProcessKpiSnapshot& Snapshot) const
{
    for (const FScenarioCheck& Check : ActiveChecks)
    {
        if (!CheckPasses(Check, Snapshot))
        {
            return true;
        }
    }
    return false;
}
