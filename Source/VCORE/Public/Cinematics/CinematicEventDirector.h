#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "CinematicEventDirector.generated.h"

class ACameraActor;

UENUM(BlueprintType)
enum class ECinematicEventKind : uint8
{
    Bottleneck,
    Collision
};

/**
 * F3 — Auto-directed camera for evaluator presentations (3D camera / rendering).
 *
 * When a noteworthy event fires, the controller calls FocusOnEvent(...); the director frames the
 * hotspot with a managed camera and blends the player's view to it (SetViewTargetWithBlend), holds
 * for a dwell time, then blends back to the overview. Severity priority + a minimum hold prevent
 * thrashing when events arrive in bursts. A manual camera selection cancels auto-direction until
 * re-enabled.
 *
 * See docs/spec_portfolio_features.md §4.
 */
UCLASS(ClassGroup=(VCORE), meta=(BlueprintSpawnableComponent))
class VCORE_API UCinematicEventDirector : public UActorComponent
{
    GENERATED_BODY()

public:
    UCinematicEventDirector();

    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

    /** Cut + blend the evaluator view to frame an event hotspot. */
    UFUNCTION(BlueprintCallable, Category="VCORE|Cinematics")
    void FocusOnEvent(ECinematicEventKind Kind, const FVector& WorldLocation, AActor* FocusActor);

    /** The actor to blend back to when a cut finishes (cell overview camera/actor). */
    UFUNCTION(BlueprintCallable, Category="VCORE|Cinematics")
    void SetOverviewTarget(AActor* Overview);

    UFUNCTION(BlueprintCallable, Category="VCORE|Cinematics")
    void SetEnabled(bool bInEnabled);

    /** Called by the manual /camera/select path so a user selection suspends auto-direction. */
    UFUNCTION(BlueprintCallable, Category="VCORE|Cinematics")
    void NotifyManualOverride();

protected:
    UPROPERTY(EditAnywhere, Category="VCORE|Cinematics", meta=(ClampMin="0.0"))
    float BlendTimeSeconds = 0.6f;

    UPROPERTY(EditAnywhere, Category="VCORE|Cinematics", meta=(ClampMin="0.1"))
    float DwellSeconds = 3.0f;

private:
    APlayerController* GetPlayerController() const;
    ACameraActor* EnsureManagedCamera();
    int32 PriorityOf(ECinematicEventKind Kind) const;
    void ReturnToOverview();

    UPROPERTY()
    TObjectPtr<ACameraActor> ManagedCamera;

    TWeakObjectPtr<AActor> OverviewTarget;

    bool bEnabled = true;
    bool bManualOverride = false;
    int32 ActivePriority = -1;

    FTimerHandle DwellTimerHandle;
};
