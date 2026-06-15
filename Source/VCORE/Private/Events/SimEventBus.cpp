#include "SimEventBus.h"

#include "Engine/Engine.h"
#include "Engine/World.h"

USimEventBus* USimEventBus::Get(const UObject* WorldContextObject)
{
    if (!GEngine || !WorldContextObject)
    {
        return nullptr;
    }

    if (const UWorld* World = GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::ReturnNull))
    {
        return World->GetSubsystem<USimEventBus>();
    }

    return nullptr;
}
