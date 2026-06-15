#pragma once

#include "CoreMinimal.h"
#include "StateTree/AGVStateTreeTaskBase.h"
#include "AGVWaitAtStationTask.generated.h"

struct FStateTreeExecutionContext;
struct FStateTreeTransitionResult;

USTRUCT()
struct FAGVWaitAtStationTaskInstanceData : public FAGVStateTreeTaskInstanceData
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, Category="Parameter", meta=(ClampMin="0.0"))
    float DurationSeconds = 1.0f;

    float RemainingSeconds = 0.0f;
};

USTRUCT(DisplayName="Wait At Station", Category="VCORE|AGV|Station")
struct VCORE_API FAGVWaitAtStationTask : public FAGVStateTreeTaskBase
{
    GENERATED_BODY()

    using FInstanceDataType = FAGVWaitAtStationTaskInstanceData;

    virtual const UStruct* GetInstanceDataType() const override { return FInstanceDataType::StaticStruct(); }
    virtual EStateTreeRunStatus EnterState(FStateTreeExecutionContext& Context, const FStateTreeTransitionResult& Transition) const override;
    virtual EStateTreeRunStatus Tick(FStateTreeExecutionContext& Context, const float DeltaTime) const override;
};
