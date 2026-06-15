#include "StateTree/AGVUnloadCargoTask.h"

#include "StateTreeExecutionContext.h"

EStateTreeRunStatus FAGVUnloadCargoTask::EnterState(FStateTreeExecutionContext& Context, const FStateTreeTransitionResult& Transition) const
{
    const FInstanceDataType& InstanceData = Context.GetInstanceData(*this);
    AAGVActor* AGV = ResolveAGV(Context, InstanceData);
    if (!IsValid(AGV))
    {
        return EStateTreeRunStatus::Failed;
    }

    return AGV->RequestStateTreeState(EAGVState::Unloading) ? EStateTreeRunStatus::Running : EStateTreeRunStatus::Failed;
}

EStateTreeRunStatus FAGVUnloadCargoTask::Tick(FStateTreeExecutionContext& Context, const float DeltaTime) const
{
    const FInstanceDataType& InstanceData = Context.GetInstanceData(*this);
    AAGVActor* AGV = ResolveAGV(Context, InstanceData);
    if (!IsValid(AGV))
    {
        return EStateTreeRunStatus::Failed;
    }

    return AGV->IsInState(EAGVState::Unloading) ? EStateTreeRunStatus::Running : EStateTreeRunStatus::Succeeded;
}
