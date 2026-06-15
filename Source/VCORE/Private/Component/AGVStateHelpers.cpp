#include "AGVStateHelpers.h"

FString FAGVStateHelpers::ToStateString(EAGVState State)
{
    switch (State)
    {
    case EAGVState::Idle:
        return TEXT("IDLE");
    case EAGVState::MovingToPickup:
        return TEXT("MOVING_TO_PICKUP");
    case EAGVState::Loading:
        return TEXT("LOADING");
    case EAGVState::MovingToDropoff:
        return TEXT("MOVING_TO_DROPOFF");
    case EAGVState::Unloading:
        return TEXT("UNLOADING");
    case EAGVState::WaitingAtSection:
        return TEXT("WAITING_AT_SECTION");
    case EAGVState::StoppedCollision:
        return TEXT("STOPPED_COLLISION");
    case EAGVState::MovingToStation:
        return TEXT("MOVING_TO_STATION");
    case EAGVState::StoppedOperation:
        return TEXT("STOPPED_OPERATION");
    default:
        return TEXT("UNKNOWN");
    }
}

EAGVTaskLifecycleState FAGVStateHelpers::ToTaskLifecycleState(EAGVState State)
{
    switch (State)
    {
    case EAGVState::Idle:
        return EAGVTaskLifecycleState::Idle;
    case EAGVState::MovingToPickup:
        return EAGVTaskLifecycleState::MovingToPickup;
    case EAGVState::Loading:
        return EAGVTaskLifecycleState::Loading;
    case EAGVState::MovingToDropoff:
        return EAGVTaskLifecycleState::MovingToDropoff;
    case EAGVState::Unloading:
        return EAGVTaskLifecycleState::Unloading;
    case EAGVState::WaitingAtSection:
        return EAGVTaskLifecycleState::WaitingForRoute;
    case EAGVState::StoppedCollision:
        return EAGVTaskLifecycleState::CollisionStopped;
    case EAGVState::MovingToStation:
        return EAGVTaskLifecycleState::MovingToStation;
    case EAGVState::StoppedOperation:
        return EAGVTaskLifecycleState::Idle;
    default:
        return EAGVTaskLifecycleState::Failed;
    }
}

bool FAGVStateHelpers::IsActiveState(EAGVState State)
{
    return State == EAGVState::MovingToPickup
        || State == EAGVState::MovingToDropoff
        || State == EAGVState::Loading
        || State == EAGVState::Unloading
        || State == EAGVState::MovingToStation;
}
