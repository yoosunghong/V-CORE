#pragma once

#include "CoreMinimal.h"
#include "Components/SphereComponent.h"
#include "StationInteractionComponent.generated.h"

class AAGVActor;

/**
 * Proximity trigger that makes an AStationActor an *active* interaction anchor.
 *
 * When an AGV overlaps this volume the owning station drives Load/Unload by proximity (replacing the
 * old hardcoded spline-ratio checkpoints) and a StationArrived event is published on the sim event
 * bus for observers. The component is a USphereComponent so it carries its own trigger geometry; the
 * station attaches one in its constructor. See docs/spec_p6_refactor.md §1–§3.
 */
UCLASS(ClassGroup=(VCORE), meta=(BlueprintSpawnableComponent))
class VCORE_API UStationInteractionComponent : public USphereComponent
{
    GENERATED_BODY()

public:
    UStationInteractionComponent();

    virtual void BeginPlay() override;

private:
    // Fires when any primitive enters the trigger; reacts only to AGVs.
    UFUNCTION()
    void HandleAgvOverlap(
        UPrimitiveComponent* OverlappedComponent,
        AActor* OtherActor,
        UPrimitiveComponent* OtherComp,
        int32 OtherBodyIndex,
        bool bFromSweep,
        const FHitResult& SweepResult);
};
