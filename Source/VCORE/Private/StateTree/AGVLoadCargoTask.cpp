#include "StateTree/AGVLoadCargoTask.h"

#include "StateTreeExecutionContext.h"

EStateTreeRunStatus FAGVLoadCargoTask::EnterState(FStateTreeExecutionContext& Context, const FStateTreeTransitionResult& Transition) const
{
    const FInstanceDataType& InstanceData = Context.GetInstanceData(*this);
    AAGVActor* AGV = ResolveAGV(Context, InstanceData);
    if (!IsValid(AGV))
    {
        return EStateTreeRunStatus::Failed;
    }

    return AGV->RequestStateTreeState(EAGVState::Loading) ? EStateTreeRunStatus::Running : EStateTreeRunStatus::Failed;
}

EStateTreeRunStatus FAGVLoadCargoTask::Tick(FStateTreeExecutionContext& Context, const float DeltaTime) const
{
    const FInstanceDataType& InstanceData = Context.GetInstanceData(*this);
    AAGVActor* AGV = ResolveAGV(Context, InstanceData);
    if (!IsValid(AGV))
    {
        return EStateTreeRunStatus::Failed;
    }

    return AGV->IsInState(EAGVState::Loading) ? EStateTreeRunStatus::Running : EStateTreeRunStatus::Succeeded;
}
