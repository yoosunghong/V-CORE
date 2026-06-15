#include "LoadObject.h"

ULoadObject* ULoadObject::Create(UObject* Outer, const FString& InLoadId, int32 InStationId, const FString& InLoadType)
{
    ULoadObject* Load = NewObject<ULoadObject>(Outer);
    Load->LoadId = InLoadId;
    Load->LoadType = InLoadType.IsEmpty() ? TEXT("generic") : InLoadType;
    Load->CurrentStationId = InStationId;
    Load->State = ELoadLifecycleState::WaitingAtStation;
    return Load;
}

void ULoadObject::MarkHeldByAgv(const FString& AgvId)
{
    CurrentHolderAgvId = AgvId;
    CurrentStationId = 0;
    State = ELoadLifecycleState::OnAgv;
}

void ULoadObject::MarkDeliveredToStation(int32 StationId)
{
    CurrentHolderAgvId.Reset();
    CurrentStationId = StationId;
    State = ELoadLifecycleState::Delivered;
}
