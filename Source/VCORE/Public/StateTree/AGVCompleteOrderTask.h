#pragma once

#include "CoreMinimal.h"
#include "StateTree/AGVStateTreeTaskBase.h"
#include "AGVCompleteOrderTask.generated.h"

struct FStateTreeExecutionContext;
struct FStateTreeTransitionResult;

USTRUCT(DisplayName="Complete Order", Category="VCORE|AGV|Order")
struct VCORE_API FAGVCompleteOrderTask : public FAGVStateTreeTaskBase
{
    GENERATED_BODY()

    using FInstanceDataType = FAGVStateTreeTaskInstanceData;

    virtual const UStruct* GetInstanceDataType() const override { return FInstanceDataType::StaticStruct(); }
    virtual EStateTreeRunStatus EnterState(FStateTreeExecutionContext& Context, const FStateTreeTransitionResult& Transition) const override;
};
