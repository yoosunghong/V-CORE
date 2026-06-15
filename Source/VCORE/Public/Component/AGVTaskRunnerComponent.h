#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "AGVTypes.h"
#include "AGVTaskRunnerComponent.generated.h"

UCLASS(ClassGroup=(VCORE), BlueprintType, meta=(BlueprintSpawnableComponent))
class VCORE_API UAGVTaskRunnerComponent : public UActorComponent
{
    GENERATED_BODY()

public:
    UAGVTaskRunnerComponent();

    void ResetForRun();
    void TickTask(float DeltaSeconds, EAGVState CurrentState);
    void OnStateChanged(EAGVState NewState);

    UPROPERTY(EditAnywhere, Category="VCORE|AGV|Task", meta=(ClampMin="0.0"))
    float ActionDurationSeconds = 1.0f;

private:
    float ActionTimeRemainingSeconds = 0.0f;
};
