#include "StationActor.h"

#include "Components/SceneComponent.h"
#include "StationInteractionComponent.h"

AStationActor::AStationActor()
{
    PrimaryActorTick.bCanEverTick = false;

    SceneRoot = CreateDefaultSubobject<USceneComponent>(TEXT("SceneRoot"));
    SetRootComponent(SceneRoot);

    DockingPose = CreateDefaultSubobject<USceneComponent>(TEXT("DockingPose"));
    DockingPose->SetupAttachment(SceneRoot);

    InteractionVolume = CreateDefaultSubobject<UStationInteractionComponent>(TEXT("InteractionVolume"));
    InteractionVolume->SetupAttachment(SceneRoot);
}

FTransform AStationActor::GetDockingTransform() const
{
    return DockingPose ? DockingPose->GetComponentTransform() : GetActorTransform();
}

bool AStationActor::ReserveForAgv(const FString& AgvId)
{
    if (AgvId.IsEmpty() || !bReady || !bAccessible)
    {
        return false;
    }

    if (!ReservedByAgvId.IsEmpty() && ReservedByAgvId != AgvId)
    {
        return false;
    }

    ReservedByAgvId = AgvId;
    return true;
}

void AStationActor::ReleaseReservation(const FString& AgvId)
{
    if (AgvId.IsEmpty() || ReservedByAgvId == AgvId)
    {
        ReservedByAgvId.Reset();
    }
}
