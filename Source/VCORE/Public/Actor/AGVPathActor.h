#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "AGVPathActor.generated.h"

class USplineComponent;
class USceneComponent;

UCLASS()
class VCORE_API AAGVPathActor : public AActor
{
    GENERATED_BODY()

public:
    AAGVPathActor();

    USplineComponent* GetPathSpline() const { return PathSpline; }

private:
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, meta=(AllowPrivateAccess="true"))
    TObjectPtr<USceneComponent> SceneRoot;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, meta=(AllowPrivateAccess="true"))
    TObjectPtr<USplineComponent> PathSpline;
};
