#pragma once

#include "CoreMinimal.h"
#include "AGVActor.h"
#include "StateTreeTaskBase.h"
#include "AGVStateTreeTaskBase.generated.h"

struct FStateTreeExecutionContext;

USTRUCT()
struct FAGVStateTreeTaskInstanceData
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, Category="Input")
    TObjectPtr<AAGVActor> AGV = nullptr;
};

USTRUCT(meta=(Hidden))
struct VCORE_API FAGVStateTreeTaskBase : public FStateTreeTaskCommonBase
{
    GENERATED_BODY()

protected:
    AAGVActor* ResolveAGV(FStateTreeExecutionContext& Context, const FAGVStateTreeTaskInstanceData& InstanceData) const;
};
