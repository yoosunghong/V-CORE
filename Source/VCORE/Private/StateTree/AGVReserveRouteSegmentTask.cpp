#include "StateTree/AGVReserveRouteSegmentTask.h"

#include "StateTreeExecutionContext.h"

namespace
{
EStateTreeRunStatus GetReservationStatus(const AAGVActor* AGV)
{
    if (!IsValid(AGV))
    {
        return EStateTreeRunStatus::Failed;
    }

    return AGV->IsWaitingForRoute() ? EStateTreeRunStatus::Running : EStateTreeRunStatus::Succeeded;
}
}

EStateTreeRunStatus FAGVReserveRouteSegmentTask::EnterState(FStateTreeExecutionContext& Context, const FStateTreeTransitionResult& Transition) const
{
    const FInstanceDataType& InstanceData = Context.GetInstanceData(*this);
    return GetReservationStatus(ResolveAGV(Context, InstanceData));
}

EStateTreeRunStatus FAGVReserveRouteSegmentTask::Tick(FStateTreeExecutionContext& Context, const float DeltaTime) const
{
    const FInstanceDataType& InstanceData = Context.GetInstanceData(*this);
    return GetReservationStatus(ResolveAGV(Context, InstanceData));
}
