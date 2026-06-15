#include "AGVTaskRunnerComponent.h"

#include "AGVActor.h"
#include "AGVTaskComponent.h"
#include "AGVMovementComponent.h"
#include "AGVSimController.h"
#include "LoadObject.h"
#include "SimEventBus.h"
#include "TransportOrder.h"

UAGVTaskRunnerComponent::UAGVTaskRunnerComponent()
{
    PrimaryComponentTick.bCanEverTick = false;
}

void UAGVTaskRunnerComponent::ResetForRun()
{
    ActionTimeRemainingSeconds = 0.0f;
}

void UAGVTaskRunnerComponent::TickTask(float DeltaSeconds, EAGVState CurrentState)
{
    AAGVActor* OwnerAgv = Cast<AAGVActor>(GetOwner());
    if (!OwnerAgv || (CurrentState != EAGVState::Loading && CurrentState != EAGVState::Unloading))
    {
        return;
    }

    ActionTimeRemainingSeconds -= DeltaSeconds;
    if (OwnerAgv->MovementComponent)
    {
        OwnerAgv->MovementComponent->SetCurrentSpeed(0.0f);
    }
    if (ActionTimeRemainingSeconds > 0.0f)
    {
        return;
    }

    if (CurrentState == EAGVState::Loading)
    {
        OwnerAgv->bCarryingLoad = true;
        if (OwnerAgv->CurrentOrder && OwnerAgv->CurrentOrder->Load)
        {
            OwnerAgv->CurrentOrder->Load->MarkHeldByAgv(OwnerAgv->AgvId);
        }
        OwnerAgv->TransitionTo(EAGVState::MovingToDropoff);
    }
    else if (CurrentState == EAGVState::Unloading)
    {
        OwnerAgv->bCarryingLoad = false;
        ++OwnerAgv->CompletedTasks;

        const double SimTimestamp = OwnerAgv->Controller ? OwnerAgv->Controller->GetSimTimestampSeconds() : 0.0;
        const double TaskDuration = FMath::Max(0.0, SimTimestamp - OwnerAgv->CurrentTaskStartedAt);
        if (OwnerAgv->Controller)
        {
            if (USimEventBus* Bus = USimEventBus::Get(this))
            {
                FSimTaskCompletedEvent TaskEvent;
                TaskEvent.AgvId = OwnerAgv->AgvId;
                TaskEvent.TaskDurationSec = TaskDuration;
                Bus->BroadcastTaskCompleted(TaskEvent);
            }
        }
        if (OwnerAgv->CurrentOrder)
        {
            OwnerAgv->CurrentOrder->MarkCompleted();
        }
        if (OwnerAgv->TaskComponent)
        {
            if (!OwnerAgv->TaskComponent->CompleteCurrentTask(SimTimestamp))
            {
                return;
            }
        }

        OwnerAgv->CurrentOrder = nullptr;
        OwnerAgv->bHasTaskAssigned = false;
        OwnerAgv->TransitionTo(EAGVState::Idle);
    }
}

void UAGVTaskRunnerComponent::OnStateChanged(EAGVState NewState)
{
    if (NewState == EAGVState::Loading || NewState == EAGVState::Unloading)
    {
        ActionTimeRemainingSeconds = ActionDurationSeconds;
    }
    else if (NewState == EAGVState::Idle)
    {
        ActionTimeRemainingSeconds = 0.0f;
    }
}
