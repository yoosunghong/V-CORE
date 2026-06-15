#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "TransportOrder.generated.h"

class ULoadObject;

UENUM(BlueprintType)
enum class ETransportOrderState : uint8
{
    Created,
    Queued,
    Assigned,
    InProgress,
    Completed,
    Failed,
    Canceled
};

UCLASS(BlueprintType)
class VCORE_API UTransportOrder : public UObject
{
    GENERATED_BODY()

public:
    UPROPERTY(BlueprintReadOnly, Category="VCORE|Order")
    FString OrderId;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Order")
    FString TaskId;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Order")
    int32 SourceStationId = 0;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Order")
    int32 DestinationStationId = 0;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Order")
    int32 TargetStationId = 0;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Order")
    int32 Priority = 0;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Order")
    ETransportOrderState State = ETransportOrderState::Created;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Order")
    FString AssignedAgvId;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Order")
    FString FailureReason;

    UPROPERTY(BlueprintReadOnly, Category="VCORE|Order")
    TObjectPtr<ULoadObject> Load;

    static UTransportOrder* CreateStationCommand(UObject* Outer, int32 StationId, ULoadObject* InLoad, int32 InPriority);

    void AssignToAgv(const FString& AgvId);
    void MarkInProgress();
    void MarkCompleted();
    void MarkFailed(const FString& InFailureReason = FString());
};
