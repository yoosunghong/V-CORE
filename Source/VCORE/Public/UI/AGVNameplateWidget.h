#pragma once

#include "CoreMinimal.h"
#include "Blueprint/UserWidget.h"
#include "AGVNameplateWidget.generated.h"

class UTextBlock;
class UProgressBar;

/**
 * UMG widget backing the AGV nameplate widget component.
 *
 * Blueprint subclasses should contain widgets named exactly TXT_AGVName, TXT_Task,
 * TXT_Status (TextBlocks) and PB_Battery (ProgressBar) so BindWidget can wire them at
 * runtime. The Task/Status/Battery binds are optional so an older Blueprint that has not
 * been re-wired yet still compiles (the C++ null-checks each before use).
 */
UCLASS(BlueprintType, Blueprintable)
class VCORE_API UAGVNameplateWidget : public UUserWidget
{
    GENERATED_BODY()

public:
    // Refresh the nameplate. Task is the AGV's current activity (e.g. LOADING); bOnline drives the
    // green "Online" / red "Offline" status label; BatteryPercent (0..100) fills the battery bar.
    UFUNCTION(BlueprintCallable, Category="VCORE|AGV")
    void SetAGVInfo(const FString& Name, const FString& Task, bool bOnline, float BatteryPercent);

protected:
    UPROPERTY(BlueprintReadOnly, meta=(BindWidget), Category="VCORE|AGV")
    TObjectPtr<UTextBlock> TXT_AGVName;

    // Current activity label (was TXT_Status; renamed to the AGV "task" — the live state name).
    UPROPERTY(BlueprintReadOnly, meta=(BindWidgetOptional), Category="VCORE|AGV")
    TObjectPtr<UTextBlock> TXT_Task;

    // Online/Offline indicator: green text "Online" while running, red "Offline" when stopped.
    UPROPERTY(BlueprintReadOnly, meta=(BindWidgetOptional), Category="VCORE|AGV")
    TObjectPtr<UTextBlock> TXT_Status;

    // Battery gauge filled to the AGV's BatteryPercent (0..1).
    UPROPERTY(BlueprintReadOnly, meta=(BindWidgetOptional), Category="VCORE|AGV")
    TObjectPtr<UProgressBar> PB_Battery;
};
