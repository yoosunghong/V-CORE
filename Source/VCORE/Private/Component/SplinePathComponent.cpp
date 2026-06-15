#include "SplinePathComponent.h"

void USplinePathComponent::ConfigureClosedLoop(const TArray<FVector>& LocalPoints)
{
    ClearSplinePoints(false);

    for (const FVector& Point : LocalPoints)
    {
        AddSplinePoint(Point, ESplineCoordinateSpace::Local, false);
    }

    SetClosedLoop(true, false);
    UpdateSpline();
}

float USplinePathComponent::GetLoopLengthSafe() const
{
    return FMath::Max(GetSplineLength(), 1.0f);
}

FVector USplinePathComponent::GetLocationAtDistanceWrapped(float Distance) const
{
    return GetLocationAtDistanceAlongSpline(WrapDistance(Distance), ESplineCoordinateSpace::World);
}

FRotator USplinePathComponent::GetRotationAtDistanceWrapped(float Distance) const
{
    return GetRotationAtDistanceAlongSpline(WrapDistance(Distance), ESplineCoordinateSpace::World);
}

float USplinePathComponent::WrapDistance(float Distance) const
{
    return FMath::Fmod(Distance + GetLoopLengthSafe(), GetLoopLengthSafe());
}
