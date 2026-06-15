#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "LoadObject.generated.h"

UENUM(BlueprintType)
enum class ELoadLifecycleState : uint8
{
    Created,
    WaitingAtStation,
    OnAgv,
    Delivered,
    Failed
};

UCLASS(BlueprintType)
class VCORE_API ULoadObject : public UObject
{
    GENERATED_BODY()

public:
    UPROPERTY(BlueprintReadOnly, Category="VCORE|Load")
    FString LoadId;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Load")
    FString LoadType = TEXT("generic");

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Load")
    ELoadLifecycleState State = ELoadLifecycleState::Created;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Load")
    int32 CurrentStationId = 0;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Load")
    FString CurrentHolderAgvId;

    static ULoadObject* Create(UObject* Outer, const FString& InLoadId, int32 InStationId, const FString& InLoadType);

    void MarkHeldByAgv(const FString& AgvId);
    void MarkDeliveredToStation(int32 StationId);
};
