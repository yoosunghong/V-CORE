#include "AGVStationRegistryComponent.h"

#include "AGVPathActor.h"
#include "Components/SplineComponent.h"
#include "Engine/World.h"
#include "EngineUtils.h"

void UAGVStationRegistryComponent::Rebuild(const TArray<TObjectPtr<AStationActor>>& AuthoredStations)
{
    StationRegistry.Empty();
    int32 AuthoredArrayCount = 0;
    int32 WorldScanCount = 0;

    for (AStationActor* Station : AuthoredStations)
    {
        if (IsValid(Station))
        {
            StationRegistry.Add(Station->GetStationId(), Station);
            ++AuthoredArrayCount;
        }
    }

    if (UWorld* World = GetWorld())
    {
        for (TActorIterator<AStationActor> It(World); It; ++It)
        {
            AStationActor* Station = *It;
            if (IsValid(Station))
            {
                StationRegistry.FindOrAdd(Station->GetStationId(), Station);
                ++WorldScanCount;
            }
        }
    }

    UE_LOG(LogTemp, Log, TEXT("AGVStationRegistry: rebuilt %d station(s) (%d authored, %d world-scan hits)"),
        StationRegistry.Num(), AuthoredArrayCount, WorldScanCount);
    for (const TPair<int32, TObjectPtr<AStationActor>>& Pair : StationRegistry)
    {
        const AStationActor* Station = Pair.Value.Get();
        if (IsValid(Station))
        {
            UE_LOG(LogTemp, Log, TEXT("AGVStationRegistry: station %d kind=%d zone=%s actor=%s"),
                Pair.Key,
                static_cast<int32>(Station->StationKind),
                *Station->ZoneId,
                *Station->GetName());
        }
    }
}

void UAGVStationRegistryComponent::Clear()
{
    StationRegistry.Empty();
}

AStationActor* UAGVStationRegistryComponent::ResolveStation(int32 StationId) const
{
    if (const TObjectPtr<AStationActor>* Station = StationRegistry.Find(StationId))
    {
        return Station->Get();
    }
    return nullptr;
}

AStationActor* UAGVStationRegistryComponent::FindNearestStationOfKind(
    const FVector& TestLocation,
    EStationKind Kind,
    float MaxDistance) const
{
    AStationActor* Best = nullptr;
    float BestDistSq = MaxDistance * MaxDistance;
    for (const TPair<int32, TObjectPtr<AStationActor>>& Pair : StationRegistry)
    {
        AStationActor* Station = Pair.Value.Get();
        if (!IsValid(Station) || Station->StationKind != Kind)
        {
            continue;
        }

        const float DistSq = static_cast<float>(FVector::DistSquared(Station->GetActorLocation(), TestLocation));
        if (DistSq <= BestDistSq)
        {
            BestDistSq = DistSq;
            Best = Station;
        }
    }
    return Best;
}

void UAGVStationRegistryComponent::EnsureInteractionStations(
    TArray<TObjectPtr<AStationActor>>& AuthoredStations,
    const TArray<TObjectPtr<AAGVPathActor>>& AuthoredPaths,
    int32 AgvCount)
{
    int32 PickupCount = 0;
    int32 DropoffCount = 0;
    int32 MaxStationId = 0;
    for (const TPair<int32, TObjectPtr<AStationActor>>& Pair : StationRegistry)
    {
        MaxStationId = FMath::Max(MaxStationId, Pair.Key);
        if (const AStationActor* Station = Pair.Value.Get())
        {
            if (Station->StationKind == EStationKind::Pickup)
            {
                ++PickupCount;
            }
            else if (Station->StationKind == EStationKind::Dropoff)
            {
                ++DropoffCount;
            }
        }
    }

    if (PickupCount > 0 && DropoffCount > 0)
    {
        return;
    }

    int32 NextStationId = MaxStationId + 1;
    const int32 PathCount = FMath::Min(AgvCount, AuthoredPaths.Num());
    for (int32 Index = 0; Index < PathCount; ++Index)
    {
        AAGVPathActor* PathActor = AuthoredPaths[Index];
        if (!IsValid(PathActor) || !PathActor->GetPathSpline())
        {
            continue;
        }

        if (PickupCount == 0)
        {
            if (AStationActor* Station = SpawnInteractionStation(PathActor, NextStationId++, EStationKind::Pickup, 0.22f))
            {
                AuthoredStations.Add(Station);
            }
        }
        if (DropoffCount == 0)
        {
            if (AStationActor* Station = SpawnInteractionStation(PathActor, NextStationId++, EStationKind::Dropoff, 0.72f))
            {
                AuthoredStations.Add(Station);
            }
        }
    }

    Rebuild(AuthoredStations);
}

AStationActor* UAGVStationRegistryComponent::SpawnInteractionStation(
    AAGVPathActor* PathActor,
    int32 StationId,
    EStationKind Kind,
    float DistanceRatio)
{
    UWorld* World = GetWorld();
    if (!World || !IsValid(PathActor) || !PathActor->GetPathSpline())
    {
        return nullptr;
    }

    USplineComponent* Spline = PathActor->GetPathSpline();
    const float Distance = DistanceRatio * FMath::Max(Spline->GetSplineLength(), 1.0f);
    const FVector Location = Spline->GetLocationAtDistanceAlongSpline(Distance, ESplineCoordinateSpace::World);
    const FRotator Rotation = Spline->GetRotationAtDistanceAlongSpline(Distance, ESplineCoordinateSpace::World);

    FActorSpawnParameters SpawnParams;
    SpawnParams.Owner = GetOwner();
    SpawnParams.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
    AStationActor* Station = World->SpawnActor<AStationActor>(AStationActor::StaticClass(), Location, Rotation, SpawnParams);
    if (IsValid(Station))
    {
        Station->StationId = StationId;
        Station->StationKind = Kind;
        Station->Tags.AddUnique(TEXT("RuntimeInteractionStation"));
    }
    return Station;
}
