#pragma once

#include "CoreMinimal.h"
#include "StateTree/AGVStateTreeTaskBase.h"
#include "AGVFailOrderTask.generated.h"

struct FStateTreeExecutionContext;
struct FStateTreeTransitionResult;

USTRUCT()
struct FAGVFailOrderTaskInstanceData : public FAGVStateTreeTaskInstanceData
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, Category="Parameter")
    FString FailureReason = TEXT("state_tree_failed");
};

USTRUCT(DisplayName="Fail Order", Category="VCORE|AGV|Order")
struct VCORE_API FAGVFailOrderTask : public FAGVStateTreeTaskBase
{
    GENERATED_BODY()

    using FInstanceDataType = FAGVFailOrderTaskInstanceData;

    virtual const UStruct* GetInstanceDataType() const override { return FInstanceDataType::StaticStruct(); }
    virtual EStateTreeRunStatus EnterState(FStateTreeExecutionContext& Context, const FStateTreeTransitionResult& Transition) const override;
};
