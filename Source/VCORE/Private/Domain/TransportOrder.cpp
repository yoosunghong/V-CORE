#include "TransportOrder.h"

#include "LoadObject.h"
#include "Misc/Guid.h"

UTransportOrder* UTransportOrder::CreateStationCommand(UObject* Outer, int32 StationId, ULoadObject* InLoad, int32 InPriority)
{
    UTransportOrder* Order = NewObject<UTransportOrder>(Outer);
    const FString Guid = FGuid::NewGuid().ToString(EGuidFormats::Digits);
    Order->OrderId = FString::Printf(TEXT("order_%s"), *Guid);
    Order->TaskId = FString::Printf(TEXT("task_%s"), *Guid);
    Order->DestinationStationId = StationId;
    Order->TargetStationId = StationId;
    Order->Priority = InPriority;
    Order->Load = InLoad;
    Order->State = ETransportOrderState::Queued;
    return Order;
}

void UTransportOrder::AssignToAgv(const FString& AgvId)
{
    AssignedAgvId = AgvId;
    FailureReason.Reset();
    State = ETransportOrderState::Assigned;
}

void UTransportOrder::MarkInProgress()
{
    State = ETransportOrderState::InProgress;
}

void UTransportOrder::MarkCompleted()
{
    FailureReason.Reset();
    State = ETransportOrderState::Completed;
}

void UTransportOrder::MarkFailed(const FString& InFailureReason)
{
    FailureReason = InFailureReason;
    State = ETransportOrderState::Failed;
}
