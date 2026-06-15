#include "StateTree/AGVMoveAlongSplineToTargetTask.h"

#include "StateTreeExecutionContext.h"

namespace
{
bool IsSupportedMovementState(EAGVState State)
{
    return State == EAGVState::MovingToPickup
        || State == EAGVState::MovingToDropoff
        || State == EAGVState::MovingToStation;
}
}

EStateTreeRunStatus FAGVMoveAlongSplineToTargetTask::EnterState(FStateTreeExecutionContext& Context, const FStateTreeTransitionResult& Transition) const
{
    const FInstanceDataType& InstanceData = Context.GetInstanceData(*this);
    AAGVActor* AGV = ResolveAGV(Context, InstanceData);
    if (!IsValid(AGV) || !IsSupportedMovementState(InstanceData.MovementState))
    {
        return EStateTreeRunStatus::Failed;
    }

    return AGV->RequestStateTreeState(InstanceData.MovementState) ? EStateTreeRunStatus::Running : EStateTreeRunStatus::Failed;
}

EStateTreeRunStatus FAGVMoveAlongSplineToTargetTask::Tick(FStateTreeExecutionContext& Context, const float DeltaTime) const
{
    const FInstanceDataType& InstanceData = Context.GetInstanceData(*this);
    AAGVActor* AGV = ResolveAGV(Context, InstanceData);
    if (!IsValid(AGV))
    {
        return EStateTreeRunStatus::Failed;
    }

    if (AGV->IsInState(EAGVState::StoppedCollision))
    {
        return EStateTreeRunStatus::Failed;
    }

    return (AGV->IsInState(InstanceData.MovementState) || AGV->IsWaitingForRoute())
        ? EStateTreeRunStatus::Running
        : EStateTreeRunStatus::Succeeded;
}
