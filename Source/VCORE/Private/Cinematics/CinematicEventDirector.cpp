#include "CinematicEventDirector.h"

#include "Camera/CameraActor.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "TimerManager.h"

UCinematicEventDirector::UCinematicEventDirector()
{
    PrimaryComponentTick.bCanEverTick = false;
}

void UCinematicEventDirector::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().ClearTimer(DwellTimerHandle);
    }
    if (ManagedCamera)
    {
        ManagedCamera->Destroy();
        ManagedCamera = nullptr;
    }
    Super::EndPlay(EndPlayReason);
}

void UCinematicEventDirector::SetOverviewTarget(AActor* Overview)
{
    OverviewTarget = Overview;
}

void UCinematicEventDirector::SetEnabled(bool bInEnabled)
{
    bEnabled = bInEnabled;
    if (bEnabled)
    {
        bManualOverride = false;
    }
}

void UCinematicEventDirector::NotifyManualOverride()
{
    bManualOverride = true;
    ActivePriority = -1;
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().ClearTimer(DwellTimerHandle);
    }
}

APlayerController* UCinematicEventDirector::GetPlayerController() const
{
    UWorld* World = GetWorld();
    return World ? World->GetFirstPlayerController() : nullptr;
}

int32 UCinematicEventDirector::PriorityOf(ECinematicEventKind Kind) const
{
    return Kind == ECinematicEventKind::Collision ? 2 : 1;
}

ACameraActor* UCinematicEventDirector::EnsureManagedCamera()
{
    if (ManagedCamera)
    {
        return ManagedCamera;
    }
    UWorld* World = GetWorld();
    if (!World)
    {
        return nullptr;
    }
    FActorSpawnParameters Params;
    Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
    ManagedCamera = World->SpawnActor<ACameraActor>(ACameraActor::StaticClass(), FTransform::Identity, Params);
    return ManagedCamera;
}

void UCinematicEventDirector::FocusOnEvent(ECinematicEventKind Kind, const FVector& WorldLocation, AActor* FocusActor)
{
    if (!bEnabled || bManualOverride)
    {
        return;
    }

    const int32 NewPriority = PriorityOf(Kind);
    // A cut already holding can only be pre-empted by an equal-or-higher severity event.
    if (ActivePriority >= 0 && NewPriority < ActivePriority)
    {
        return;
    }

    APlayerController* PC = GetPlayerController();
    ACameraActor* Camera = EnsureManagedCamera();
    if (!PC || !Camera)
    {
        return;
    }

    // Frame the hotspot: collisions get a low, close dramatic angle; bottlenecks a higher survey.
    const bool bCollision = (Kind == ECinematicEventKind::Collision);
    const float Back = bCollision ? 420.0f : 700.0f;
    const float Height = bCollision ? 180.0f : 520.0f;
    const FVector CamLocation = WorldLocation + FVector(-Back, -Back, Height);
    const FRotator CamRotation = (WorldLocation - CamLocation).Rotation();
    Camera->SetActorLocationAndRotation(CamLocation, CamRotation);

    PC->SetViewTargetWithBlend(Camera, BlendTimeSeconds, EViewTargetBlendFunction::VTBlend_Cubic);
    ActivePriority = NewPriority;

    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().ClearTimer(DwellTimerHandle);
        FTimerDelegate Delegate = FTimerDelegate::CreateUObject(this, &UCinematicEventDirector::ReturnToOverview);
        World->GetTimerManager().SetTimer(DwellTimerHandle, Delegate, DwellSeconds, false);
    }
}

void UCinematicEventDirector::ReturnToOverview()
{
    ActivePriority = -1;
    if (bManualOverride)
    {
        return;
    }
    APlayerController* PC = GetPlayerController();
    AActor* Overview = OverviewTarget.Get();
    if (PC && Overview)
    {
        PC->SetViewTargetWithBlend(Overview, BlendTimeSeconds, EViewTargetBlendFunction::VTBlend_Cubic);
    }
}
