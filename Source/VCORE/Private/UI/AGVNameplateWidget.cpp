#include "AGVNameplateWidget.h"

#include "Components/ProgressBar.h"
#include "Components/TextBlock.h"

void UAGVNameplateWidget::SetAGVInfo(const FString& Name, const FString& Task, bool bOnline, float BatteryPercent)
{
    if (TXT_AGVName)
    {
        TXT_AGVName->SetText(FText::FromString(Name));
    }

    if (TXT_Task)
    {
        TXT_Task->SetText(FText::FromString(Task));
    }

    if (TXT_Status)
    {
        TXT_Status->SetText(FText::FromString(bOnline ? TEXT("Online") : TEXT("Offline")));
        const FLinearColor StatusColor = bOnline
            ? FLinearColor(0.16f, 0.78f, 0.27f)   // green — running
            : FLinearColor(0.86f, 0.18f, 0.18f);  // red — stopped
        TXT_Status->SetColorAndOpacity(FSlateColor(StatusColor));
    }

    if (PB_Battery)
    {
        PB_Battery->SetPercent(FMath::Clamp(BatteryPercent / 100.0f, 0.0f, 1.0f));
    }
}
