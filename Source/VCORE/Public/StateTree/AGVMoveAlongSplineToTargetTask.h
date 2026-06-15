#pragma once

#include "CoreMinimal.h"
#include "StateTree/AGVStateTreeTaskBase.h"
#include "AGVMoveAlongSplineToTargetTask.generated.h"

struct FStateTreeExecutionContext;
struct FStateTreeTransitionResult;

USTRUCT()
struct FAGVMoveAlongSplineToTargetTaskInstanceData : public FAGVStateTreeTaskInstanceData
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, Category="Parameter")
    EAGVState MovementState = EAGVState::MovingToPickup;
};

USTRUCT(DisplayName="Move Along Spline To Target", Category="VCORE|AGV|Movement")
struct VCORE_API FAGVMoveAlongSplineToTargetTask : public FAGVStateTreeTaskBase
{
    GENERATED_BODY()

    using FInstanceDataType = FAGVMoveAlongSplineToTargetTaskInstanceData;

    virtual const UStruct* GetInstanceDataType() const override { return FInstanceDataType::StaticStruct(); }
    virtual EStateTreeRunStatus EnterState(FStateTreeExecutionContext& Context, const FStateTreeTransitionResult& Transition) const override;
    virtual EStateTreeRunStatus Tick(FStateTreeExecutionContext& Context, const float DeltaTime) const override;
};
