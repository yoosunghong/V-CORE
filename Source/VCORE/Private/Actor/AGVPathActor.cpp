#include "AGVPathActor.h"

#include "Components/SceneComponent.h"
#include "Components/SplineComponent.h"

AAGVPathActor::AAGVPathActor()
{
    PrimaryActorTick.bCanEverTick = false;

    SceneRoot = CreateDefaultSubobject<USceneComponent>(TEXT("SceneRoot"));
    SetRootComponent(SceneRoot);

    PathSpline = CreateDefaultSubobject<USplineComponent>(TEXT("PathSpline"));
    PathSpline->SetupAttachment(SceneRoot);
    PathSpline->SetClosedLoop(true);
}
