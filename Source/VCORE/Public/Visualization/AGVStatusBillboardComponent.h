#pragma once

#include "CoreMinimal.h"
#include "Components/SceneComponent.h"
#include "AGVStatusBillboardComponent.generated.h"

class AAGVActor;
class UTextRenderComponent;

/**
 * F2 — Live, camera-facing status label above an AGV (data-driven world-space rendering).
 *
 * Owns a child UTextRenderComponent (engine-only, no UMG asset). Each throttled tick it reads the
 * tracked AGV's existing getters and rebuilds the label text + colour (green = active, amber =
 * waiting, red = collision), and billboards the text toward the active camera so it stays readable
 * from any viewpoint. Self-contained: an AAGVActor attaches one and calls SetTrackedAgv(this).
 *
 * See docs/spec_portfolio_features.md §3.
 */
UCLASS(ClassGroup=(VCORE), meta=(BlueprintSpawnableComponent))
class VCORE_API UAGVStatusBillboardComponent : public USceneComponent
{
    GENERATED_BODY()

public:
    UAGVStatusBillboardComponent();

    virtual void BeginPlay() override;
    virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

    UFUNCTION(BlueprintCallable, Category="VCORE|Visualization")
    void SetTrackedAgv(AAGVActor* Agv);

    UFUNCTION(BlueprintCallable, Category="VCORE|Visualization")
    void SetVisibleState(bool bStatusVisible);

protected:
    UPROPERTY(VisibleAnywhere, Category="VCORE|Visualization")
    TObjectPtr<UTextRenderComponent> Label;

    /** Label refresh rate (Hz). */
    UPROPERTY(EditAnywhere, Category="VCORE|Visualization", meta=(ClampMin="1.0"))
    float RefreshRateHz = 5.0f;

    /** Height above the AGV origin to float the label. */
    UPROPERTY(EditAnywhere, Category="VCORE|Visualization")
    float HeightOffset = 140.0f;

private:
    void RefreshLabel();
    void FaceActiveCamera();

    TWeakObjectPtr<AAGVActor> TrackedAgv;
    float SecondsSinceRefresh = 0.0f;
};
