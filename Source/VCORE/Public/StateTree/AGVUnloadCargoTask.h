#pragma once

#include "CoreMinimal.h"
#include "StateTree/AGVStateTreeTaskBase.h"
#include "AGVUnloadCargoTask.generated.h"

struct FStateTreeExecutionContext;
struct FStateTreeTransitionResult;

USTRUCT(DisplayName="Unload Cargo", Category="VCORE|AGV|Cargo")
struct VCORE_API FAGVUnloadCargoTask : public FAGVStateTreeTaskBase
{
    GENERATED_BODY()

    using FInstanceDataType = FAGVStateTreeTaskInstanceData;

    virtual const UStruct* GetInstanceDataType() const override { return FInstanceDataType::StaticStruct(); }
    virtual EStateTreeRunStatus EnterState(FStateTreeExecutionContext& Context, const FStateTreeTransitionResult& Transition) const override;
    virtual EStateTreeRunStatus Tick(FStateTreeExecutionContext& Context, const float DeltaTime) const override;
};
