#include "AGVTaskComponent.h"

#include "Components/StateTreeComponent.h"
#include "NativeGameplayTags.h"
#include "StateTree.h"
#include "TransportOrder.h"

UE_DEFINE_GAMEPLAY_TAG_STATIC(TAG_VCore_AGV_Control_StartRun, "VCORE.AGV.Control.StartRun");
UE_DEFINE_GAMEPLAY_TAG_STATIC(TAG_VCore_AGV_Control_StopRun, "VCORE.AGV.Control.StopRun");
UE_DEFINE_GAMEPLAY_TAG_STATIC(TAG_VCore_AGV_Control_AssignOrder, "VCORE.AGV.Control.AssignOrder");
UE_DEFINE_GAMEPLAY_TAG_STATIC(TAG_VCore_AGV_Control_CompleteTask, "VCORE.AGV.Control.CompleteTask");
UE_DEFINE_GAMEPLAY_TAG_STATIC(TAG_VCore_AGV_Control_FailTask, "VCORE.AGV.Control.FailTask");

UE_DEFINE_GAMEPLAY_TAG_STATIC(TAG_VCore_AGV_State_Offline, "VCORE.AGV.State.Offline");
UE_DEFINE_GAMEPLAY_TAG_STATIC(TAG_VCore_AGV_State_Idle, "VCORE.AGV.State.Idle");
UE_DEFINE_GAMEPLAY_TAG_STATIC(TAG_VCore_AGV_State_Assigned, "VCORE.AGV.State.Assigned");
UE_DEFINE_GAMEPLAY_TAG_STATIC(TAG_VCore_AGV_State_MovingToPickup, "VCORE.AGV.State.MovingToPickup");
UE_DEFINE_GAMEPLAY_TAG_STATIC(TAG_VCore_AGV_State_Loading, "VCORE.AGV.State.Loading");
UE_DEFINE_GAMEPLAY_TAG_STATIC(TAG_VCore_AGV_State_MovingToDropoff, "VCORE.AGV.State.MovingToDropoff");
UE_DEFINE_GAMEPLAY_TAG_STATIC(TAG_VCore_AGV_State_Unloading, "VCORE.AGV.State.Unloading");
UE_DEFINE_GAMEPLAY_TAG_STATIC(TAG_VCore_AGV_State_MovingToStation, "VCORE.AGV.State.MovingToStation");
UE_DEFINE_GAMEPLAY_TAG_STATIC(TAG_VCore_AGV_State_WaitingForRoute, "VCORE.AGV.State.WaitingForRoute");
UE_DEFINE_GAMEPLAY_TAG_STATIC(TAG_VCore_AGV_State_Completed, "VCORE.AGV.State.Completed");
UE_DEFINE_GAMEPLAY_TAG_STATIC(TAG_VCore_AGV_State_Failed, "VCORE.AGV.State.Failed");
UE_DEFINE_GAMEPLAY_TAG_STATIC(TAG_VCore_AGV_State_CollisionStopped, "VCORE.AGV.State.CollisionStopped");

UAGVTaskComponent::UAGVTaskComponent()
{
    PrimaryComponentTick.bCanEverTick = false;
}

void UAGVTaskComponent::BindStateTreeComponent(UStateTreeComponent* InStateTreeComponent)
{
    StateTreeComponent = InStateTreeComponent;
    if (StateTreeComponent)
    {
        StateTreeComponent->SetStartLogicAutomatically(false);
    }
}

bool UAGVTaskComponent::ResetForRun(const FString& InAgvId, double TimestampSeconds)
{
    AgvId = InAgvId;
    if (!StartStateTreeControl())
    {
        return !bRequireStateTreeForControl;
    }
    if (!DispatchControlEvent(TAG_VCore_AGV_Control_StartRun, TEXT("start_run"), TimestampSeconds))
    {
        return false;
    }

    CurrentOrder = nullptr;
    TargetStationId = 0;
    FailureReason.Reset();
    LastTransitionTimestampSeconds = TimestampSeconds;
    return TransitionTo(EAGVTaskLifecycleState::Idle, TimestampSeconds, TEXT("run_started"));
}

bool UAGVTaskComponent::StopRun(double TimestampSeconds)
{
    DispatchControlEvent(TAG_VCore_AGV_Control_StopRun, TEXT("stop_run"), TimestampSeconds);
    CurrentOrder = nullptr;
    TargetStationId = 0;
    const bool bTransitioned = TransitionTo(EAGVTaskLifecycleState::Offline, TimestampSeconds, TEXT("run_stopped"));
    StopStateTreeControl(TEXT("run_stopped"));
    return bTransitioned;
}

bool UAGVTaskComponent::AssignOrder(UTransportOrder* Order, int32 InTargetStationId, double TimestampSeconds)
{
    if (!DispatchControlEvent(TAG_VCore_AGV_Control_AssignOrder, TEXT("assign_order"), TimestampSeconds))
    {
        return false;
    }

    CurrentOrder = Order;
    TargetStationId = InTargetStationId;
    FailureReason.Reset();
    return TransitionTo(EAGVTaskLifecycleState::Assigned, TimestampSeconds, TEXT("order_assigned"));
}

bool UAGVTaskComponent::TransitionTo(EAGVTaskLifecycleState NewState, double TimestampSeconds, const FString& Reason)
{
    if (!CanExecuteControlOperation(TEXT("transition")))
    {
        return false;
    }

    if (LifecycleState == NewState)
    {
        LastTransitionTimestampSeconds = TimestampSeconds;
        return true;
    }

    const EAGVTaskLifecycleState PreviousState = LifecycleState;
    LifecycleState = NewState;
    LastTransitionTimestampSeconds = TimestampSeconds;
    DispatchLifecycleEvent(NewState, TimestampSeconds, Reason);
    OnLifecycleChanged.Broadcast(PreviousState, LifecycleState, Reason);
    return true;
}

bool UAGVTaskComponent::CompleteCurrentTask(double TimestampSeconds)
{
    if (!DispatchControlEvent(TAG_VCore_AGV_Control_CompleteTask, TEXT("complete_task"), TimestampSeconds))
    {
        return false;
    }

    if (!TransitionTo(EAGVTaskLifecycleState::Completed, TimestampSeconds, TEXT("task_completed")))
    {
        return false;
    }
    CurrentOrder = nullptr;
    TargetStationId = 0;
    FailureReason.Reset();
    return TransitionTo(EAGVTaskLifecycleState::Idle, TimestampSeconds, TEXT("ready"));
}

bool UAGVTaskComponent::FailCurrentTask(const FString& InFailureReason, double TimestampSeconds)
{
    if (!DispatchControlEvent(TAG_VCore_AGV_Control_FailTask, TEXT("fail_task"), TimestampSeconds))
    {
        return false;
    }

    FailureReason = InFailureReason;
    if (CurrentOrder)
    {
        CurrentOrder->MarkFailed(InFailureReason);
    }
    return TransitionTo(EAGVTaskLifecycleState::Failed, TimestampSeconds, FailureReason);
}

FString UAGVTaskComponent::GetLifecycleStateName() const
{
    return LifecycleStateToString(LifecycleState);
}

FString UAGVTaskComponent::LifecycleStateToString(EAGVTaskLifecycleState State)
{
    switch (State)
    {
    case EAGVTaskLifecycleState::Offline:
        return TEXT("OFFLINE");
    case EAGVTaskLifecycleState::Idle:
        return TEXT("IDLE");
    case EAGVTaskLifecycleState::Assigned:
        return TEXT("ASSIGNED");
    case EAGVTaskLifecycleState::MovingToPickup:
        return TEXT("MOVING_TO_PICKUP");
    case EAGVTaskLifecycleState::Loading:
        return TEXT("LOADING");
    case EAGVTaskLifecycleState::MovingToDropoff:
        return TEXT("MOVING_TO_DROPOFF");
    case EAGVTaskLifecycleState::Unloading:
        return TEXT("UNLOADING");
    case EAGVTaskLifecycleState::MovingToStation:
        return TEXT("MOVING_TO_STATION");
    case EAGVTaskLifecycleState::WaitingForRoute:
        return TEXT("WAITING_FOR_ROUTE");
    case EAGVTaskLifecycleState::Completed:
        return TEXT("COMPLETED");
    case EAGVTaskLifecycleState::Failed:
        return TEXT("FAILED");
    case EAGVTaskLifecycleState::CollisionStopped:
        return TEXT("COLLISION_STOPPED");
    default:
        return TEXT("UNKNOWN");
    }
}

bool UAGVTaskComponent::IsStateTreeControlReady() const
{
    return StateTreeComponent && StateTreeComponent->IsRunning();
}

bool UAGVTaskComponent::StartStateTreeControl()
{
    if (!StateTreeComponent)
    {
        UE_LOG(LogTemp, Warning, TEXT("AGVTaskComponent[%s]: StateTree control component is missing"), *AgvId);
        return false;
    }

    if (!LifecycleStateTree.IsNull() && !StateTreeComponent->IsRunning())
    {
        UStateTree* LoadedStateTree = LifecycleStateTree.LoadSynchronous();
        StateTreeComponent->SetStateTree(LoadedStateTree);
    }

    if (!StateTreeComponent->IsRunning())
    {
        StateTreeComponent->StartLogic();
    }

    if (!StateTreeComponent->IsRunning())
    {
        UE_LOG(LogTemp, Warning, TEXT("AGVTaskComponent[%s]: StateTree control is not running. Assign a valid LifecycleStateTree asset with StateTreeComponentSchema."), *AgvId);
        return false;
    }

    return true;
}

void UAGVTaskComponent::StopStateTreeControl(const FString& Reason)
{
    if (StateTreeComponent && StateTreeComponent->IsRunning())
    {
        StateTreeComponent->StopLogic(Reason);
    }
}

bool UAGVTaskComponent::DispatchControlEvent(const FGameplayTag& EventTag, const FString& OperationName, double TimestampSeconds)
{
    LastControlOperation = OperationName;
    LastTransitionTimestampSeconds = TimestampSeconds;

    if (!CanExecuteControlOperation(OperationName))
    {
        return false;
    }

    if (StateTreeComponent && StateTreeComponent->IsRunning() && EventTag.IsValid())
    {
        StateTreeComponent->SendStateTreeEvent(EventTag, FConstStructView(), FName(*OperationName));
    }

    return true;
}

bool UAGVTaskComponent::DispatchLifecycleEvent(EAGVTaskLifecycleState NewState, double TimestampSeconds, const FString& Reason)
{
    LastTransitionTimestampSeconds = TimestampSeconds;
    const FGameplayTag EventTag = GetLifecycleEventTag(NewState);
    if (StateTreeComponent && StateTreeComponent->IsRunning() && EventTag.IsValid())
    {
        StateTreeComponent->SendStateTreeEvent(EventTag, FConstStructView(), FName(*Reason));
    }
    return true;
}

bool UAGVTaskComponent::CanExecuteControlOperation(const FString& OperationName) const
{
    if (!bRequireStateTreeForControl)
    {
        return true;
    }

    if (StateTreeComponent && StateTreeComponent->IsRunning())
    {
        return true;
    }

    UE_LOG(LogTemp, Warning, TEXT("AGVTaskComponent[%s]: blocking '%s' because StateTree control is required but not running"), *AgvId, *OperationName);
    return false;
}

FGameplayTag UAGVTaskComponent::GetLifecycleEventTag(EAGVTaskLifecycleState State)
{
    switch (State)
    {
    case EAGVTaskLifecycleState::Offline:
        return TAG_VCore_AGV_State_Offline;
    case EAGVTaskLifecycleState::Idle:
        return TAG_VCore_AGV_State_Idle;
    case EAGVTaskLifecycleState::Assigned:
        return TAG_VCore_AGV_State_Assigned;
    case EAGVTaskLifecycleState::MovingToPickup:
        return TAG_VCore_AGV_State_MovingToPickup;
    case EAGVTaskLifecycleState::Loading:
        return TAG_VCore_AGV_State_Loading;
    case EAGVTaskLifecycleState::MovingToDropoff:
        return TAG_VCore_AGV_State_MovingToDropoff;
    case EAGVTaskLifecycleState::Unloading:
        return TAG_VCore_AGV_State_Unloading;
    case EAGVTaskLifecycleState::MovingToStation:
        return TAG_VCore_AGV_State_MovingToStation;
    case EAGVTaskLifecycleState::WaitingForRoute:
        return TAG_VCore_AGV_State_WaitingForRoute;
    case EAGVTaskLifecycleState::Completed:
        return TAG_VCore_AGV_State_Completed;
    case EAGVTaskLifecycleState::Failed:
        return TAG_VCore_AGV_State_Failed;
    case EAGVTaskLifecycleState::CollisionStopped:
        return TAG_VCore_AGV_State_CollisionStopped;
    default:
        return FGameplayTag();
    }
}
