#include "StateTree/AGVWaitAtStationTask.h"

#include "StateTreeExecutionContext.h"

EStateTreeRunStatus FAGVWaitAtStationTask::EnterState(FStateTreeExecutionContext& Context, const FStateTreeTransitionResult& Transition) const
{
    FInstanceDataType& InstanceData = Context.GetInstanceData(*this);
    if (!IsValid(ResolveAGV(Context, InstanceData)))
    {
        return EStateTreeRunStatus::Failed;
    }

    InstanceData.RemainingSeconds = InstanceData.DurationSeconds;
    return InstanceData.RemainingSeconds > 0.0f ? EStateTreeRunStatus::Running : EStateTreeRunStatus::Succeeded;
}

EStateTreeRunStatus FAGVWaitAtStationTask::Tick(FStateTreeExecutionContext& Context, const float DeltaTime) const
{
    FInstanceDataType& InstanceData = Context.GetInstanceData(*this);
    if (!IsValid(ResolveAGV(Context, InstanceData)))
    {
        return EStateTreeRunStatus::Failed;
    }

    InstanceData.RemainingSeconds -= DeltaTime;
    return InstanceData.RemainingSeconds > 0.0f ? EStateTreeRunStatus::Running : EStateTreeRunStatus::Succeeded;
}
