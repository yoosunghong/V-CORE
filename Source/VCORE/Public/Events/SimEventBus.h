#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "SimEventTypes.h"
#include "SimEventBus.generated.h"

// C++-only multicast delegates — producers and subscribers are all engine-side, so the lighter
// non-dynamic form is used rather than BP-facing dynamic delegates.
DECLARE_MULTICAST_DELEGATE_OneParam(FOnSimAgvStateChanged, const FSimAgvStateChangedEvent&);
DECLARE_MULTICAST_DELEGATE_OneParam(FOnSimStationArrived, const FSimStationArrivedEvent&);
DECLARE_MULTICAST_DELEGATE_OneParam(FOnSimTaskCompleted, const FSimTaskCompletedEvent&);
DECLARE_MULTICAST_DELEGATE_OneParam(FOnSimCollision, const FSimCollisionEvent&);
DECLARE_MULTICAST_DELEGATE_OneParam(FOnSimBottleneck, const FSimBottleneckEvent&);

/**
 * PIE-scoped, sim-wide event relay. Domain producers (AGV, traffic, stations) Broadcast*; the
 * controller subscribes once and bridges events to KPI/backend/cinematics — keeping the Net/Domain
 * layering intact (producers never hold a Net/ reference). Being a UWorldSubsystem makes it
 * auto-created and auto-reset per PIE world. See docs/spec_p6_refactor.md §3.
 */
UCLASS()
class VCORE_API USimEventBus : public UWorldSubsystem
{
    GENERATED_BODY()

public:
    /** Resolves the bus for any world-context object; null outside a game world. */
    static USimEventBus* Get(const UObject* WorldContextObject);

    FOnSimAgvStateChanged OnAgvStateChanged;
    FOnSimStationArrived OnStationArrived;
    FOnSimTaskCompleted OnTaskCompleted;
    FOnSimCollision OnCollision;
    FOnSimBottleneck OnBottleneck;

    void BroadcastAgvStateChanged(const FSimAgvStateChangedEvent& Event) const { OnAgvStateChanged.Broadcast(Event); }
    void BroadcastStationArrived(const FSimStationArrivedEvent& Event) const { OnStationArrived.Broadcast(Event); }
    void BroadcastTaskCompleted(const FSimTaskCompletedEvent& Event) const { OnTaskCompleted.Broadcast(Event); }
    void BroadcastCollision(const FSimCollisionEvent& Event) const { OnCollision.Broadcast(Event); }
    void BroadcastBottleneck(const FSimBottleneckEvent& Event) const { OnBottleneck.Broadcast(Event); }
};
