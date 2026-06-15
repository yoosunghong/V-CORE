#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "StationActor.generated.h"

class USceneComponent;
class UStationInteractionComponent;

UENUM(BlueprintType)
enum class EStationKind : uint8
{
    Generic,
    Pickup,
    Dropoff,
    Charger,
    Inspection
};

UCLASS()
class VCORE_API AStationActor : public AActor
{
    GENERATED_BODY()

public:
    AStationActor();

    UFUNCTION(BlueprintPure, Category="VCORE|Station")
    int32 GetStationId() const { return StationId; }

    UFUNCTION(BlueprintPure, Category="VCORE|Station")
    FTransform GetDockingTransform() const;

    UFUNCTION(BlueprintPure, Category="VCORE|Station")
    bool IsAvailable() const { return bReady && bAccessible && ReservedByAgvId.IsEmpty(); }

    UFUNCTION(BlueprintCallable, Category="VCORE|Station")
    bool ReserveForAgv(const FString& AgvId);

    UFUNCTION(BlueprintCallable, Category="VCORE|Station")
    void ReleaseReservation(const FString& AgvId);

    UFUNCTION(BlueprintPure, Category="VCORE|Station")
    FString GetReservedByAgvId() const { return ReservedByAgvId; }

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="VCORE|Station")
    int32 StationId = 1;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="VCORE|Station")
    EStationKind StationKind = EStationKind::Generic;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="VCORE|Station")
    int32 Capacity = 1;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="VCORE|Station")
    FString ZoneId;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="VCORE|Station")
    TArray<FName> CapabilityTags;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="VCORE|Station")
    bool bReady = true;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="VCORE|Station")
    bool bAccessible = true;

private:
    UPROPERTY(VisibleAnywhere, Category="VCORE|Station")
    TObjectPtr<USceneComponent> SceneRoot;

    UPROPERTY(VisibleAnywhere, Category="VCORE|Station")
    TObjectPtr<USceneComponent> DockingPose;

    // Proximity trigger; an overlapping AGV drives Load/Unload off StationKind (P6.1b).
    UPROPERTY(VisibleAnywhere, Category="VCORE|Station")
    TObjectPtr<UStationInteractionComponent> InteractionVolume;

    UPROPERTY(VisibleInstanceOnly, Category="VCORE|Station")
    FString ReservedByAgvId;
};
