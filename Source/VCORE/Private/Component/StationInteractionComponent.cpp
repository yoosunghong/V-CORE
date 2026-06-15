#include "StationInteractionComponent.h"

#include "AGVActor.h"
#include "SimEventBus.h"
#include "StationActor.h"
#include "Engine/CollisionProfile.h"

namespace
{
FString StationKindToString(EStationKind Kind)
{
    switch (Kind)
    {
    case EStationKind::Pickup:     return TEXT("PICKUP");
    case EStationKind::Dropoff:    return TEXT("DROPOFF");
    case EStationKind::Charger:    return TEXT("CHARGER");
    case EStationKind::Inspection: return TEXT("INSPECTION");
    default:                       return TEXT("GENERIC");
    }
}
}

UStationInteractionComponent::UStationInteractionComponent()
{
    PrimaryComponentTick.bCanEverTick = false;

    InitSphereRadius(250.0f);
    // Mirror the AGV's own Pawn-profile sphere (query-only) so AGV overlaps fire exactly as the
    // proven AGV-AGV overlap path does, regardless of project channel response overrides.
    SetCollisionProfileName(UCollisionProfile::Pawn_ProfileName);
    SetCollisionEnabled(ECollisionEnabled::QueryOnly);
    SetGenerateOverlapEvents(true);
}

void UStationInteractionComponent::BeginPlay()
{
    Super::BeginPlay();
    OnComponentBeginOverlap.AddDynamic(this, &UStationInteractionComponent::HandleAgvOverlap);
}

void UStationInteractionComponent::HandleAgvOverlap(
    UPrimitiveComponent* /*OverlappedComponent*/,
    AActor* OtherActor,
    UPrimitiveComponent* /*OtherComp*/,
    int32 /*OtherBodyIndex*/,
    bool /*bFromSweep*/,
    const FHitResult& /*SweepResult*/)
{
    AAGVActor* Agv = Cast<AAGVActor>(OtherActor);
    AStationActor* Station = Cast<AStationActor>(GetOwner());
    if (!IsValid(Agv) || !IsValid(Station))
    {
        return;
    }

    // Observers (HUD/telemetry) hear about the arrival; the AGV is driven directly so the action is
    // deterministic and not dependent on bus subscription order.
    if (USimEventBus* Bus = USimEventBus::Get(this))
    {
        FSimStationArrivedEvent Event;
        Event.AgvId = Agv->GetAgvId();
        Event.StationId = Station->GetStationId();
        Event.StationKind = StationKindToString(Station->StationKind);
        Bus->BroadcastStationArrived(Event);
    }

    Agv->HandleStationArrival(Station);
}
