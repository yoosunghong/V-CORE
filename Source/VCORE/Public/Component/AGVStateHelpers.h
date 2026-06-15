#pragma once

#include "AGVTaskComponent.h"
#include "AGVTypes.h"

struct VCORE_API FAGVStateHelpers
{
    static FString ToStateString(EAGVState State);
    static EAGVTaskLifecycleState ToTaskLifecycleState(EAGVState State);
    static bool IsActiveState(EAGVState State);
};
