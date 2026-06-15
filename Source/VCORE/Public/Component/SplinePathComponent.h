#pragma once

#include "CoreMinimal.h"
#include "Components/SplineComponent.h"
#include "SplinePathComponent.generated.h"

UCLASS(ClassGroup=(Custom), meta=(BlueprintSpawnableComponent))
class VCORE_API USplinePathComponent : public USplineComponent
{
    GENERATED_BODY()

public:
    void ConfigureClosedLoop(const TArray<FVector>& LocalPoints);
    float GetLoopLengthSafe() const;
    FVector GetLocationAtDistanceWrapped(float Distance) const;
    FRotator GetRotationAtDistanceWrapped(float Distance) const;
    float WrapDistance(float Distance) const;
};
