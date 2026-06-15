#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "CongestionHeatmapComponent.generated.h"

class UMaterialParameterCollection;
class UDecalComponent;
class UMaterialInstanceDynamic;
class UMaterialInterface;
class UTexture2D;

/**
 * F1 — Real-time congestion heatmap (data-driven 3D visualization).
 *
 * Samples registered AGV world positions, accumulates a decaying 2D density grid over the cell
 * floor, and exposes the result both as a render hook (writes peak density + hotspot location into
 * an optional MaterialParameterCollection so a floor decal/material can colour the heat) and as a
 * query API for other systems (e.g. the Cinematic Event Director asking "where is the worst
 * congestion?").
 *
 * Domain/presentation only — no network dependency. Intended owner: AGVSimController (or the future
 * Simulation/ orchestrator). See docs/spec_portfolio_features.md §2.
 */
UCLASS(ClassGroup=(VCORE), meta=(BlueprintSpawnableComponent))
class VCORE_API UCongestionHeatmapComponent : public UActorComponent
{
    GENERATED_BODY()

public:
    UCongestionHeatmapComponent();

    virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

    /** Register a spawned AGV actor whose position contributes to the density field. */
    UFUNCTION(BlueprintCallable, Category="VCORE|Visualization")
    void RegisterAgv(AActor* Agv);

    UFUNCTION(BlueprintCallable, Category="VCORE|Visualization")
    void ClearAgvs();

    /** Floor rectangle the grid maps over, in world space (XY plane). */
    UFUNCTION(BlueprintCallable, Category="VCORE|Visualization")
    void SetFloorBounds(const FVector& Origin, const FVector2D& Size);

    /** Normalized density (0..1) at a world location; 0 if outside bounds or no data. */
    UFUNCTION(BlueprintCallable, Category="VCORE|Visualization")
    float GetNormalizedDensityAt(const FVector& WorldLocation) const;

    /** World location + normalized density of the busiest cell. Returns false if the field is empty. */
    UFUNCTION(BlueprintCallable, Category="VCORE|Visualization")
    bool GetHottestCell(FVector& OutWorldLocation, float& OutDensity) const;

    /** Runtime-generated 2D density field. Sample this in M_FloorHeat for the actual floor heatmap. */
    UFUNCTION(BlueprintCallable, Category="VCORE|Visualization")
    UTexture2D* GetHeatTexture() const { return HeatTexture; }

    /** Flat density array (size GridResX * GridResY, row-major Y). Used to serialize the final heatmap into the run report. */
    const TArray<float>& GetDensityArray() const { return Density; }

    /** Cell visit mask matching Density. Used so bottleneck calculations exclude untouched floor cells. */
    const TArray<uint8>& GetVisitedCells() const { return VisitedCells; }

    int32 GetGridResX() const { return GridResX; }
    int32 GetGridResY() const { return GridResY; }

protected:
    /** Optional. If set, peak density + hotspot are pushed here for a floor decal/material to read. */
    UPROPERTY(EditAnywhere, Category="VCORE|Visualization")
    TSoftObjectPtr<UMaterialParameterCollection> HeatParameterCollection;

    /** Optional. If set, this component creates and maintains a floor decal using this material. */
    UPROPERTY(EditAnywhere, Category="VCORE|Visualization|Render")
    TSoftObjectPtr<UMaterialInterface> FloorHeatMaterial;

    /** Creates an owner-attached decal automatically when FloorHeatMaterial is assigned. */
    UPROPERTY(EditAnywhere, Category="VCORE|Visualization|Render")
    bool bCreateManagedDecal = true;

    /** Scalar parameter (0..1) written into the MPC each update. */
    UPROPERTY(EditAnywhere, Category="VCORE|Visualization")
    FName PeakDensityParameter = TEXT("PeakDensity");

    /** Vector parameter (xyz = world hotspot) written into the MPC each update. */
    UPROPERTY(EditAnywhere, Category="VCORE|Visualization")
    FName HotspotParameter = TEXT("HotspotLocation");

    /** Texture parameter on FloorHeatMaterial receiving the runtime density texture. */
    UPROPERTY(EditAnywhere, Category="VCORE|Visualization|Render")
    FName HeatTextureParameter = TEXT("HeatTexture");

    /** Vector parameter (xy = world floor origin, zw = floor size) written to FloorHeatMaterial. */
    UPROPERTY(EditAnywhere, Category="VCORE|Visualization|Render")
    FName FloorBoundsParameter = TEXT("FloorBounds");

    /** Decal projection height/depth in world units. X is depth, Y/Z are set from floor bounds. */
    UPROPERTY(EditAnywhere, Category="VCORE|Visualization|Render", meta=(ClampMin="1.0"))
    float DecalProjectionDepth = 512.0f;

    /** Raises the managed decal above the configured floor plane. */
    UPROPERTY(EditAnywhere, Category="VCORE|Visualization|Render")
    float DecalHeightOffset = 256.0f;

    UPROPERTY(EditAnywhere, Category="VCORE|Visualization", meta=(ClampMin="2", ClampMax="128"))
    int32 GridResX = 24;

    UPROPERTY(EditAnywhere, Category="VCORE|Visualization", meta=(ClampMin="2", ClampMax="128"))
    int32 GridResY = 24;

    /** Seconds for accumulated heat to halve when a cell is unoccupied. */
    UPROPERTY(EditAnywhere, Category="VCORE|Visualization", meta=(ClampMin="0.1"))
    float DecayHalfLifeSeconds = 2.0f;

    /** Density sampled at most this many times per second. */
    UPROPERTY(EditAnywhere, Category="VCORE|Visualization", meta=(ClampMin="1.0"))
    float SampleRateHz = 10.0f;

private:
    void EnsureGrid();
    bool LocationToCell(const FVector& WorldLocation, int32& OutCX, int32& OutCY) const;
    FVector CellToLocation(int32 CX, int32 CY) const;
    void PushToMaterialParameterCollection();
    void EnsureHeatTexture();
    void UpdateHeatTexture();
    void EnsureManagedDecal();
    void UpdateManagedDecalParameters();

    FVector FloorOrigin = FVector::ZeroVector;
    FVector2D FloorSize = FVector2D(2000.0f, 2000.0f);

    TArray<float> Density;       // size GridResX * GridResY
    TArray<uint8> VisitedCells;  // size GridResX * GridResY
    float PeakDensity = 0.0f;    // running max for normalization
    float SecondsSinceSample = 0.0f;

    TArray<TWeakObjectPtr<AActor>> TrackedAgvs;

    UPROPERTY(Transient)
    TObjectPtr<UTexture2D> HeatTexture = nullptr;

    UPROPERTY(Transient)
    TObjectPtr<UMaterialInstanceDynamic> FloorHeatMaterialInstance = nullptr;

    UPROPERTY(Transient)
    TObjectPtr<UDecalComponent> ManagedDecal = nullptr;
};
