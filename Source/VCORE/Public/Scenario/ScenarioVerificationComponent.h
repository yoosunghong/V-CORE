#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "ScenarioVerificationComponent.generated.h"

/** KPI metric an acceptance criterion can assert on. */
UENUM(BlueprintType)
enum class EScenarioMetric : uint8
{
    Throughput,      // tasks / simulated hour
    AvgWaitSec,      // mean section wait time
    CollisionCount,  // total collisions this run
    UptimeRatio,     // 0..1 fraction of time AGVs are in active task states
    ActiveAgvs       // count of AGVs in an active state
};

UENUM(BlueprintType)
enum class EScenarioCompare : uint8
{
    GreaterOrEqual,
    LessOrEqual,
    Equal
};

/** One acceptance criterion attached by the AI agent to a run. */
USTRUCT(BlueprintType)
struct FScenarioCheck
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadWrite, Category="VCORE|Scenario")
    FString Label;

    UPROPERTY(BlueprintReadWrite, Category="VCORE|Scenario")
    EScenarioMetric Metric = EScenarioMetric::Throughput;

    UPROPERTY(BlueprintReadWrite, Category="VCORE|Scenario")
    EScenarioCompare Comparator = EScenarioCompare::GreaterOrEqual;

    UPROPERTY(BlueprintReadWrite, Category="VCORE|Scenario")
    float Threshold = 0.0f;
};

/** Compact KPI record evaluated against the checks (mirrors the backend ProcessTelemetry fields). */
USTRUCT(BlueprintType)
struct FProcessKpiSnapshot
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadWrite, Category="VCORE|Scenario")
    float Throughput = 0.0f;

    UPROPERTY(BlueprintReadWrite, Category="VCORE|Scenario")
    float AvgWaitSec = 0.0f;

    UPROPERTY(BlueprintReadWrite, Category="VCORE|Scenario")
    int32 CollisionCount = 0;

    UPROPERTY(BlueprintReadWrite, Category="VCORE|Scenario")
    float UptimeRatio = 0.0f;

    UPROPERTY(BlueprintReadWrite, Category="VCORE|Scenario")
    int32 ActiveAgvs = 0;
};

/** Result of evaluating all checks against a snapshot. */
USTRUCT(BlueprintType)
struct FScenarioVerdict
{
    GENERATED_BODY()

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Scenario")
    bool bPassed = true;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Scenario")
    TArray<FString> PassedLabels;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Scenario")
    TArray<FString> FailedLabels;
};

/**
 * F4 — Agent-driven scenario verification (AI-agent scenario design & verification).
 *
 * The AI agent attaches acceptance criteria to a run; this component evaluates them against the
 * live + final KPI snapshot and produces a machine-readable PASS/FAIL verdict the agent reads back
 * and explains in chat. Domain-only — boundary parsing of the agent's `acceptance[]` payload lives
 * in AGVSimController (Net layer); this component receives already-typed FScenarioChecks.
 *
 * See docs/spec_portfolio_features.md §5.
 */
UCLASS(ClassGroup=(VCORE), meta=(BlueprintSpawnableComponent))
class VCORE_API UScenarioVerificationComponent : public UActorComponent
{
    GENERATED_BODY()

public:
    UScenarioVerificationComponent();

    /** Replace the active acceptance criteria (typically once at run start). */
    UFUNCTION(BlueprintCallable, Category="VCORE|Scenario")
    void LoadChecks(const TArray<FScenarioCheck>& Checks);

    UFUNCTION(BlueprintCallable, Category="VCORE|Scenario")
    void ClearChecks();

    UFUNCTION(BlueprintCallable, Category="VCORE|Scenario")
    bool HasChecks() const { return ActiveChecks.Num() > 0; }

    /** Evaluate every check against a snapshot; overall pass requires all checks to pass. */
    UFUNCTION(BlueprintCallable, Category="VCORE|Scenario")
    FScenarioVerdict Evaluate(const FProcessKpiSnapshot& Snapshot) const;

    /** True if any check is already violated mid-run (optional early-abort signal). */
    UFUNCTION(BlueprintCallable, Category="VCORE|Scenario")
    bool HasHardViolation(const FProcessKpiSnapshot& Snapshot) const;

private:
    static float MetricValue(const FProcessKpiSnapshot& Snapshot, EScenarioMetric Metric);
    static bool CheckPasses(const FScenarioCheck& Check, const FProcessKpiSnapshot& Snapshot);

    UPROPERTY()
    TArray<FScenarioCheck> ActiveChecks;
};
