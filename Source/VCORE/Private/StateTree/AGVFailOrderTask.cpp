#include "StateTree/AGVFailOrderTask.h"

#include "StateTreeExecutionContext.h"

EStateTreeRunStatus FAGVFailOrderTask::EnterState(FStateTreeExecutionContext& Context, const FStateTreeTransitionResult& Transition) const
{
    const FInstanceDataType& InstanceData = Context.GetInstanceData(*this);
    AAGVActor* AGV = ResolveAGV(Context, InstanceData);
    if (!IsValid(AGV))
    {
        return EStateTreeRunStatus::Failed;
    }

    return AGV->FailStateTreeOrder(InstanceData.FailureReason) ? EStateTreeRunStatus::Succeeded : EStateTreeRunStatus::Failed;
}
