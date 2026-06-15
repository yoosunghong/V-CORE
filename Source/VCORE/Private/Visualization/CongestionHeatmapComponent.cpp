#include "CongestionHeatmapComponent.h"

#include "Components/DecalComponent.h"
#include "Engine/World.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialParameterCollection.h"
#include "Materials/MaterialParameterCollectionInstance.h"
#include "Materials/MaterialInterface.h"
#include "TextureResource.h"

UCongestionHeatmapComponent::UCongestionHeatmapComponent()
{
    PrimaryComponentTick.bCanEverTick = true;
}

void UCongestionHeatmapComponent::RegisterAgv(AActor* Agv)
{
    if (Agv)
    {
        TrackedAgvs.AddUnique(Agv);
    }
}

void UCongestionHeatmapComponent::ClearAgvs()
{
    TrackedAgvs.Reset();
    Density.Reset();
    VisitedCells.Reset();
    PeakDensity = 0.0f;
}

void UCongestionHeatmapComponent::SetFloorBounds(const FVector& Origin, const FVector2D& Size)
{
    FloorOrigin = Origin;
    FloorSize = FVector2D(FMath::Max(1.0f, Size.X), FMath::Max(1.0f, Size.Y));
    UpdateManagedDecalParameters();
}

void UCongestionHeatmapComponent::EnsureGrid()
{
    const int32 Expected = FMath::Max(1, GridResX) * FMath::Max(1, GridResY);
    if (Density.Num() != Expected)
    {
        Density.Init(0.0f, Expected);
        VisitedCells.Init(0, Expected);
        PeakDensity = 0.0f;
    }
    else if (VisitedCells.Num() != Expected)
    {
        VisitedCells.Init(0, Expected);
    }
    EnsureHeatTexture();
    EnsureManagedDecal();
}

bool UCongestionHeatmapComponent::LocationToCell(const FVector& WorldLocation, int32& OutCX, int32& OutCY) const
{
    const float U = (WorldLocation.X - FloorOrigin.X) / FloorSize.X;
    const float V = (WorldLocation.Y - FloorOrigin.Y) / FloorSize.Y;
    if (U < 0.0f || U >= 1.0f || V < 0.0f || V >= 1.0f)
    {
        return false;
    }
    OutCX = FMath::Clamp(FMath::FloorToInt(U * GridResX), 0, GridResX - 1);
    OutCY = FMath::Clamp(FMath::FloorToInt(V * GridResY), 0, GridResY - 1);
    return true;
}

FVector UCongestionHeatmapComponent::CellToLocation(int32 CX, int32 CY) const
{
    const float U = (CX + 0.5f) / GridResX;
    const float V = (CY + 0.5f) / GridResY;
    return FVector(FloorOrigin.X + U * FloorSize.X, FloorOrigin.Y + V * FloorSize.Y, FloorOrigin.Z);
}

void UCongestionHeatmapComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
    Super::TickComponent(DeltaTime, TickType, ThisTickFunction);

    SecondsSinceSample += DeltaTime;
    const float SampleInterval = 1.0f / FMath::Max(1.0f, SampleRateHz);
    if (SecondsSinceSample < SampleInterval)
    {
        return;
    }
    const float Elapsed = SecondsSinceSample;
    SecondsSinceSample = 0.0f;

    EnsureGrid();

    // Temporal decay so stale heat fades.
    const float DecayFactor = FMath::Pow(0.5f, Elapsed / FMath::Max(0.1f, DecayHalfLifeSeconds));
    for (float& Cell : Density)
    {
        Cell *= DecayFactor;
    }

    // Deposit current AGV occupancy.
    for (int32 i = TrackedAgvs.Num() - 1; i >= 0; --i)
    {
        AActor* Agv = TrackedAgvs[i].Get();
        if (!Agv)
        {
            TrackedAgvs.RemoveAtSwap(i);
            continue;
        }
        int32 CX = 0;
        int32 CY = 0;
        if (LocationToCell(Agv->GetActorLocation(), CX, CY))
        {
            const int32 CellIndex = CY * GridResX + CX;
            Density[CellIndex] += 1.0f;
            if (VisitedCells.IsValidIndex(CellIndex))
            {
                VisitedCells[CellIndex] = 1;
            }
        }
    }

    // Refresh running peak.
    PeakDensity = 0.0f;
    for (const float Cell : Density)
    {
        PeakDensity = FMath::Max(PeakDensity, Cell);
    }

    PushToMaterialParameterCollection();
    UpdateHeatTexture();
    UpdateManagedDecalParameters();
}

float UCongestionHeatmapComponent::GetNormalizedDensityAt(const FVector& WorldLocation) const
{
    if (PeakDensity <= KINDA_SMALL_NUMBER || Density.Num() == 0)
    {
        return 0.0f;
    }
    int32 CX = 0;
    int32 CY = 0;
    if (!LocationToCell(WorldLocation, CX, CY))
    {
        return 0.0f;
    }
    return FMath::Clamp(Density[CY * GridResX + CX] / PeakDensity, 0.0f, 1.0f);
}

bool UCongestionHeatmapComponent::GetHottestCell(FVector& OutWorldLocation, float& OutDensity) const
{
    if (PeakDensity <= KINDA_SMALL_NUMBER || Density.Num() == 0)
    {
        return false;
    }
    int32 BestIndex = INDEX_NONE;
    float Best = 0.0f;
    for (int32 i = 0; i < Density.Num(); ++i)
    {
        if (Density[i] > Best)
        {
            Best = Density[i];
            BestIndex = i;
        }
    }
    if (BestIndex == INDEX_NONE)
    {
        return false;
    }
    const int32 CX = BestIndex % GridResX;
    const int32 CY = BestIndex / GridResX;
    OutWorldLocation = CellToLocation(CX, CY);
    OutDensity = FMath::Clamp(Best / PeakDensity, 0.0f, 1.0f);
    return true;
}

void UCongestionHeatmapComponent::PushToMaterialParameterCollection()
{
    UMaterialParameterCollection* Collection = HeatParameterCollection.LoadSynchronous();
    if (!Collection)
    {
        return;
    }
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }
    UMaterialParameterCollectionInstance* Instance = World->GetParameterCollectionInstance(Collection);
    if (!Instance)
    {
        return;
    }

    FVector Hotspot = FloorOrigin;
    float Density01 = 0.0f;
    GetHottestCell(Hotspot, Density01);

    Instance->SetScalarParameterValue(PeakDensityParameter, Density01);
    Instance->SetVectorParameterValue(HotspotParameter, FLinearColor(Hotspot.X, Hotspot.Y, Hotspot.Z, 1.0f));
}

void UCongestionHeatmapComponent::EnsureHeatTexture()
{
    const int32 Width = FMath::Max(1, GridResX);
    const int32 Height = FMath::Max(1, GridResY);
    if (HeatTexture && HeatTexture->GetSizeX() == Width && HeatTexture->GetSizeY() == Height)
    {
        return;
    }

    HeatTexture = UTexture2D::CreateTransient(Width, Height, PF_B8G8R8A8, TEXT("VCORE_CongestionHeat"));
    if (!HeatTexture)
    {
        return;
    }

    HeatTexture->CompressionSettings = TC_VectorDisplacementmap;
    HeatTexture->MipGenSettings = TMGS_NoMipmaps;
    HeatTexture->SRGB = false;
    HeatTexture->Filter = TF_Bilinear;
    HeatTexture->UpdateResource();

    if (FloorHeatMaterialInstance)
    {
        FloorHeatMaterialInstance->SetTextureParameterValue(HeatTextureParameter, HeatTexture);
    }
}

void UCongestionHeatmapComponent::UpdateHeatTexture()
{
    EnsureHeatTexture();
    if (!HeatTexture || Density.Num() == 0)
    {
        return;
    }

    const int32 Width = HeatTexture->GetSizeX();
    const int32 Height = HeatTexture->GetSizeY();
    const int32 PixelCount = Width * Height;
    uint8* PixelData = new uint8[PixelCount * 4];

    for (int32 Y = 0; Y < Height; ++Y)
    {
        for (int32 X = 0; X < Width; ++X)
        {
            const int32 SourceIndex = Y * Width + X;
            const float Normalized = (PeakDensity > KINDA_SMALL_NUMBER && Density.IsValidIndex(SourceIndex))
                ? FMath::Clamp(Density[SourceIndex] / PeakDensity, 0.0f, 1.0f)
                : 0.0f;
            const uint8 Value = static_cast<uint8>(FMath::RoundToInt(Normalized * 255.0f));

            const int32 PixelIndex = SourceIndex * 4;
            PixelData[PixelIndex + 0] = Value;
            PixelData[PixelIndex + 1] = Value;
            PixelData[PixelIndex + 2] = Value;
            PixelData[PixelIndex + 3] = Value;
        }
    }

    FUpdateTextureRegion2D* Region = new FUpdateTextureRegion2D(0, 0, 0, 0, Width, Height);
    HeatTexture->UpdateTextureRegions(
        0,
        1,
        Region,
        Width * 4,
        4,
        PixelData,
        [](uint8* SrcData, const FUpdateTextureRegion2D* Regions)
        {
            delete[] SrcData;
            delete Regions;
        });
}

void UCongestionHeatmapComponent::EnsureManagedDecal()
{
    if (!bCreateManagedDecal)
    {
        return;
    }

    UMaterialInterface* Material = FloorHeatMaterial.LoadSynchronous();
    AActor* Owner = GetOwner();
    if (!Material || !Owner)
    {
        return;
    }

    if (!FloorHeatMaterialInstance)
    {
        FloorHeatMaterialInstance = UMaterialInstanceDynamic::Create(Material, this);
        if (HeatTexture)
        {
            FloorHeatMaterialInstance->SetTextureParameterValue(HeatTextureParameter, HeatTexture);
        }
    }

    if (!ManagedDecal)
    {
        ManagedDecal = NewObject<UDecalComponent>(Owner, TEXT("CongestionHeatmapDecal"));
        ManagedDecal->SetupAttachment(Owner->GetRootComponent());
        ManagedDecal->RegisterComponent();
        Owner->AddInstanceComponent(ManagedDecal);
    }

    if (ManagedDecal && FloorHeatMaterialInstance)
    {
        ManagedDecal->SetDecalMaterial(FloorHeatMaterialInstance);
    }
}

void UCongestionHeatmapComponent::UpdateManagedDecalParameters()
{
    EnsureManagedDecal();

    if (FloorHeatMaterialInstance)
    {
        FloorHeatMaterialInstance->SetVectorParameterValue(
            FloorBoundsParameter,
            FLinearColor(FloorOrigin.X, FloorOrigin.Y, FloorSize.X, FloorSize.Y));
    }

    if (!ManagedDecal)
    {
        return;
    }

    const FVector Center(
        FloorOrigin.X + FloorSize.X * 0.5f,
        FloorOrigin.Y + FloorSize.Y * 0.5f,
        FloorOrigin.Z + DecalHeightOffset);

    ManagedDecal->SetWorldLocation(Center);
    ManagedDecal->SetWorldRotation(FRotator(-90.0f, 0.0f, 0.0f));
    ManagedDecal->DecalSize = FVector(
        FMath::Max(1.0f, DecalProjectionDepth),
        FMath::Max(1.0f, FloorSize.X * 0.5f),
        FMath::Max(1.0f, FloorSize.Y * 0.5f));
}
