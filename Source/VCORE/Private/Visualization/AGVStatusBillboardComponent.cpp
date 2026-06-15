#include "AGVStatusBillboardComponent.h"

#include "AGVActor.h"
#include "Camera/PlayerCameraManager.h"
#include "Components/TextRenderComponent.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"

UAGVStatusBillboardComponent::UAGVStatusBillboardComponent()
{
    PrimaryComponentTick.bCanEverTick = true;
}

void UAGVStatusBillboardComponent::BeginPlay()
{
    Super::BeginPlay();

    // The label is created at runtime rather than as a constructor default subobject:
    // a nested CreateDefaultSubobject inside a component constructor crosses the
    // CDO-template / instance attachment when this component lives on a Blueprint
    // subclass (BP_AGVActor), tripping the "Template Mismatch during attachment" ensure.
    if (!Label)
    {
        Label = NewObject<UTextRenderComponent>(this, TEXT("StatusLabel"));
        Label->SetupAttachment(this);
        Label->SetHorizontalAlignment(EHTA_Center);
        Label->SetVerticalAlignment(EVRTA_TextCenter);
        Label->SetWorldSize(28.0f);
        Label->SetText(FText::GetEmpty());
        Label->RegisterComponent();
    }

    if (!TrackedAgv.IsValid())
    {
        // Default to the owning actor if it is an AGV and no explicit target was set.
        SetTrackedAgv(Cast<AAGVActor>(GetOwner()));
    }
    SetRelativeLocation(FVector(0.0f, 0.0f, HeightOffset));
}

void UAGVStatusBillboardComponent::SetTrackedAgv(AAGVActor* Agv)
{
    TrackedAgv = Agv;
}

void UAGVStatusBillboardComponent::SetVisibleState(bool bStatusVisible)
{
    if (Label)
    {
        Label->SetVisibility(bStatusVisible, true);
    }
}

void UAGVStatusBillboardComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
    Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

    SecondsSinceRefresh += DeltaTime;
    const float Interval = 1.0f / FMath::Max(1.0f, RefreshRateHz);
    if (SecondsSinceRefresh >= Interval)
    {
        SecondsSinceRefresh = 0.0f;
        RefreshLabel();
    }

    FaceActiveCamera();
}

void UAGVStatusBillboardComponent::RefreshLabel()
{
    AAGVActor* Agv = TrackedAgv.Get();
    if (!Agv || !Label)
    {
        return;
    }

    const FString StateName = Agv->GetStateName();
    const FString Text = FString::Printf(
        TEXT("%s\n%s\n%d%%  %.1f m/s"),
        *Agv->GetAgvId(),
        *StateName,
        FMath::RoundToInt(Agv->GetBatteryPercent()),
        Agv->GetCurrentSpeed());
    Label->SetText(FText::FromString(Text));

    FColor Colour = FColor(80, 220, 120); // active = green
    if (StateName.Contains(TEXT("Collision")))
    {
        Colour = FColor(230, 70, 70); // red
    }
    else if (StateName.Contains(TEXT("Waiting")))
    {
        Colour = FColor(235, 180, 60); // amber
    }
    Label->SetTextRenderColor(Colour);
}

void UAGVStatusBillboardComponent::FaceActiveCamera()
{
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }
    APlayerController* PC = World->GetFirstPlayerController();
    if (!PC || !PC->PlayerCameraManager)
    {
        return;
    }

    const FVector CamLocation = PC->PlayerCameraManager->GetCameraLocation();
    const FVector ToCamera = CamLocation - GetComponentLocation();
    if (ToCamera.IsNearlyZero())
    {
        return;
    }
    // TextRender's readable face looks down +X; rotate so that face points at the camera.
    FRotator LookRotation = (-ToCamera).Rotation();
    LookRotation.Pitch = 0.0f;
    LookRotation.Roll = 0.0f;
    SetWorldRotation(LookRotation);
}
