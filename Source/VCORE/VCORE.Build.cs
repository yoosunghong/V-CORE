// Copyright Epic Games, Inc. All Rights Reserved.

using UnrealBuildTool;

public class VCORE : ModuleRules
{
	public VCORE(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[] {
			"Core",
			"CoreUObject",
			"Engine",
			"InputCore",
			"EnhancedInput",
			"AIModule",
			"NavigationSystem",
			"GameplayTags",
			"StateTreeModule",
			"GameplayStateTreeModule",
			"Niagara",
			"UMG",
			"Slate",
			"SlateCore",
			"WebSockets",
			"HTTP",
			"HTTPServer",
			"Json",
			"JsonUtilities",
			"Sockets",
			"Networking"
		});

		PrivateDependencyModuleNames.AddRange(new string[] { });

		PublicIncludePaths.AddRange(new string[] {
			"VCORE",
			// Purpose-partitioned public headers (bare-name includes resolve from these).
			"VCORE/public/Actor",
			"VCORE/public/Component",
			"VCORE/public/Controller",
			"VCORE/public/Core",
			"VCORE/public/Domain",
			"VCORE/public/Events",
			"VCORE/public/Visualization",
			"VCORE/public/Cinematics",
			"VCORE/public/Scenario",
            "VCORE/public/UI",
		});

		// Uncomment if you are using Slate UI
		// PrivateDependencyModuleNames.AddRange(new string[] { "Slate", "SlateCore" });

		// Uncomment if you are using online features
		// PrivateDependencyModuleNames.Add("OnlineSubsystem");

		// To include OnlineSubsystemSteam, add it to the plugins section in your uproject file with the Enabled attribute set to true
	}
}
