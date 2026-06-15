#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "VirtualProcessGameMode.generated.h"

/**
 * Minimal GameMode for the Virtual Process digital-twin scene. Inherits all default behaviour from
 * GameModeBase. Set this as the Warehouse map's GameMode Override (or GlobalDefaultGameMode).
 *
 * The HUD is now rendered by the web overlay (chat-web), fed from the process telemetry frame, so
 * this GameMode no longer installs an in-viewport HUD.
 *
 * Also satisfies Phase 8 P0 "author the Virtual Process GameMode".
 */
UCLASS()
class VCORE_API AVirtualProcessGameMode : public AGameModeBase
{
    GENERATED_BODY()

public:
    AVirtualProcessGameMode();
};
