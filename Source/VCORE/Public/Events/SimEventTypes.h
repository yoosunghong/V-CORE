#pragma once

#include "CoreMinimal.h"
#include "SimEventTypes.generated.h"

// Payload structs for the sim-wide event bus (USimEventBus). See docs/spec_p6_refactor.md §3.
// P6.1a wired the four events that had direct Emit*/Notify* calls; P6.1b adds StationArrived; the
// reservation events join in P6.2 once the unified traffic manager produces them.

/** An AGV's task/motion state changed (was AAGVSimController::EmitAgvStateChange). */
USTRUCT()
struct FSimAgvStateChangedEvent
{
    GENERATED_BODY()

    UPROPERTY() FString AgvId;
    UPROPERTY() FString FromState;
    UPROPERTY() FString ToState;
    UPROPERTY() float Speed = 0.0f;
    UPROPERTY() float Battery = 0.0f;
};

/** An AGV entered a station's interaction volume (producer: UStationInteractionComponent). */
USTRUCT()
struct FSimStationArrivedEvent
{
    GENERATED_BODY()

    UPROPERTY() FString AgvId;
    UPROPERTY() int32 StationId = 0;
    UPROPERTY() FString StationKind;
};

/** An AGV finished a delivery task (was AAGVSimController::NotifyTaskCompleted). */
USTRUCT()
struct FSimTaskCompletedEvent
{
    GENERATED_BODY()

    UPROPERTY() FString AgvId;
    UPROPERTY() double TaskDurationSec = 0.0;
};

/** Two AGVs collided (was AAGVSimController::NotifyCollision). */
USTRUCT()
struct FSimCollisionEvent
{
    GENERATED_BODY()

    UPROPERTY() FString AgvIdA;
    UPROPERTY() FString AgvIdB;
    UPROPERTY() FVector Position = FVector::ZeroVector;
    UPROPERTY() float RelativeVelocity = 0.0f;
};

/** An AGV waited past the bottleneck threshold at a reserved segment (was EmitBottleneckEvent). */
USTRUCT()
struct FSimBottleneckEvent
{
    GENERATED_BODY()

    UPROPERTY() FString AgvId;
    UPROPERTY() FString SectionId;
    UPROPERTY() double WaitDurationSec = 0.0;
    UPROPERTY() TArray<FString> QueuedAgvIds;
};
