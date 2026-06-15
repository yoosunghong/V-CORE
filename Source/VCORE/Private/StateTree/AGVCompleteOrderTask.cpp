#include "StateTree/AGVCompleteOrderTask.h"

#include "StateTreeExecutionContext.h"

EStateTreeRunStatus FAGVCompleteOrderTask::EnterState(FStateTreeExecutionContext& Context, const FStateTreeTransitionResult& Transition) const
{
    const FInstanceDataType& InstanceData = Context.GetInstanceData(*this);
    AAGVActor* AGV = ResolveAGV(Context, InstanceData);
    if (!IsValid(AGV))
    {
        return EStateTreeRunStatus::Failed;
    }

    return AGV->CompleteStateTreeOrder() ? EStateTreeRunStatus::Succeeded : EStateTreeRunStatus::Failed;
}
