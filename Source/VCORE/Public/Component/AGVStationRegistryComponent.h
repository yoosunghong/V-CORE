#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "StationActor.h"
#include "AGVStationRegistryComponent.generated.h"

class AAGVPathActor;

UCLASS(ClassGroup=(VCORE), meta=(BlueprintSpawnableComponent))
class VCORE_API UAGVStationRegistryComponent : public UActorComponent
{
    GENERATED_BODY()

public:
    void Rebuild(const TArray<TObjectPtr<AStationActor>>& AuthoredStations);
    void Clear();

    int32 Num() const { return StationRegistry.Num(); }
    const TMap<int32, TObjectPtr<AStationActor>>& GetStations() const { return StationRegistry; }

    AStationActor* ResolveStation(int32 StationId) const;
    AStationActor* FindNearestStationOfKind(const FVector& TestLocation, EStationKind Kind, float MaxDistance) const;

    void EnsureInteractionStations(
        TArray<TObjectPtr<AStationActor>>& AuthoredStations,
        const TArray<TObjectPtr<AAGVPathActor>>& AuthoredPaths,
        int32 AgvCount);

private:
    AStationActor* SpawnInteractionStation(AAGVPathActor* PathActor, int32 StationId, EStationKind Kind, float DistanceRatio);

    UPROPERTY(Transient)
    TMap<int32, TObjectPtr<AStationActor>> StationRegistry;
};
