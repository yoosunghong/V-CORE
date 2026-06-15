#include "StateTree/AGVStateTreeTaskBase.h"

#include "Components/ActorComponent.h"
#include "StateTreeExecutionContext.h"

AAGVActor* FAGVStateTreeTaskBase::ResolveAGV(FStateTreeExecutionContext& Context, const FAGVStateTreeTaskInstanceData& InstanceData) const
{
    if (IsValid(InstanceData.AGV))
    {
        return InstanceData.AGV;
    }

    UObject* Owner = Context.GetOwner();
    if (AAGVActor* OwnerAGV = Cast<AAGVActor>(Owner))
    {
        return OwnerAGV;
    }

    if (const UActorComponent* OwnerComponent = Cast<UActorComponent>(Owner))
    {
        return Cast<AAGVActor>(OwnerComponent->GetOwner());
    }

    return nullptr;
}
