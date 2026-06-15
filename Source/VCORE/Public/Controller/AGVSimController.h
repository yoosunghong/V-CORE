#pragma once

#include "CoreMinimal.h"
#include "AGVSimTypes.h"
#include "Containers/Array.h"
#include "GameFramework/Actor.h"
#include "TimerManager.h"
#include "IWebSocket.h"
#include "HttpRouteHandle.h"
#include "Templates/SharedPointer.h"

class AAGVActor;
class ADispatcherActor;
class AAGVPathActor;
class AIntersectionManager;
class AStationActor;
class ATrafficManagerActor;
class UCinematicEventDirector;
class UCongestionHeatmapComponent;
class UKPIAccumulator;
class UScenarioVerificationComponent;
class ULoadObject;
class UTransportOrder;
class USimEventBus;
class UAGVStationRegistryComponent;
class UAGVTelemetryComponent;
enum class EStationKind : uint8;
struct FSimAgvStateChangedEvent;
struct FSimStationArrivedEvent;
struct FSimTaskCompletedEvent;
struct FSimCollisionEvent;
struct FSimBottleneckEvent;
class FJsonObject;
struct IConsoleCommand;
struct FDispatchScoreBreakdown;

#include "AGVSimController.generated.h"

UCLASS()
class VCORE_API AAGVSimController : public AActor
{
    GENERATED_BODY()

public:
    AAGVSimController();

    virtual void BeginPlay() override;
    virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
    virtual void Tick(float DeltaSeconds) override;

    // Called by AGVActor/SimEventDispatcher to stream a real-time event to the backend.
    void SendSimEvent(const TSharedRef<FJsonObject>& EventJson);

    // Called by KPIAccumulator at simulation end to submit the final report.
    void SendSimComplete(const TSharedRef<FJsonObject>& ReportJson);

    double GetSimTimestampSeconds() const;
    int32 GetTotalTasksCompleted() const;

    // Snapshot streamed on the process telemetry frame; rendered by the web overlay HUD.
    FVcoreHudSnapshot GetHudSnapshot() const;

    // Called by an AGVActor when it reaches a station anchor commanded via /agv/command.
    // Emits the chat-correlated robot.command.completed for the pending command.
    void OnAgvReachedStation(AAGVActor* Agv, int32 StationId);

    // Nearest registered station of the given kind within MaxDistance of TestLocation, or nullptr.
    // Lets an AGV register an autonomous Pickup/Dropoff arrival by distance ??a deterministic
    // complement to the UStationInteractionComponent physics overlap.
    AStationActor* FindNearestStationOfKind(const FVector& TestLocation, EStationKind Kind, float MaxDistance) const;

    // --- PIE test harness ---------------------------------------------------
    // Drive the AGV cell inside PIE without the chatbot backend / :7777 HTTP path.
    // Registered as real console commands (Exec UFUNCTIONs don't route on a plain
    // AActor). Open the console (~) and type e.g.
    //   Vcore.Start [Speed] [AgvCount]
    //   Vcore.Assign <agvIndex>
    //   Vcore.Station <agvIndex> <stationId>
    //   Vcore.Stop
    void VcoreStart(float Speed = 4.0f, int32 AgvCount = 3);
    void VcoreStop();
    void VcoreAssign(int32 AgvIndex = 0);
    void VcoreStation(int32 AgvIndex = 0, int32 StationId = 1);

    FSimStartParams ActiveParams;
    bool bSimRunning = false;
    bool bSimPaused = false;
    // Latched once a run has been ended by a full-fleet collision halt, so the per-Tick
    // collision check fires CompleteRuntimeRun exactly once (bSimRunning stays true until reset).
    bool bCollisionHaltCompleted = false;
    float SpeedMultiplier = 1.0f;

    // Chat correlation for the most recent agent-issued command. UE5 echoes these
    // back on emitted chat events so the backend can route progress to the session.
    FString ActiveSessionId;
    FString ActiveCorrelationId;
    FString ActiveCommandId;

    // Pre-placed AGV actors in the level. On sim start, the first AgvCount entries are
    // configured and activated; the rest remain offline. Never destroyed between runs.
    UPROPERTY(EditInstanceOnly, BlueprintReadWrite, Category="VCORE|Simulation")
    TArray<TObjectPtr<AAGVActor>> AuthoredAgvs;

    UPROPERTY(EditInstanceOnly, BlueprintReadWrite, Category="VCORE|Simulation")
    TArray<TObjectPtr<AAGVPathActor>> AuthoredPaths;

    UPROPERTY(EditInstanceOnly, BlueprintReadWrite, Category="VCORE|Simulation")
    TArray<TObjectPtr<AStationActor>> AuthoredStations;

    // Distance (cm) within which two active AGVs are considered a collision. Tunable
    // per-level; the tick-based check fires ForceCollisionStop on both AGVs.
    UPROPERTY(EditAnywhere, Category="VCORE|Simulation", meta=(ClampMin="50.0"))
    float CollisionDetectionRadius = 300.0f;

    // Delay between successive AGV launches at sim start. The first AGV moves immediately, the
    // next AgvStartStaggerSeconds later, and so on — so the cell never starts with every unit
    // approaching its path at once. 0 disables staggering.
    UPROPERTY(EditAnywhere, Category="VCORE|Simulation", meta=(ClampMin="0.0"))
    float AgvStartStaggerSeconds = 5.0f;

private:
    static constexpr int32 MaxWebSocketConnectRetries = 3;

    // PIE test-harness console commands (registered in BeginPlay, freed in EndPlay).
    void RegisterDebugConsoleCommands();
    void UnregisterDebugConsoleCommands();
    TArray<IConsoleCommand*> DebugConsoleCommands;

    FString BackendHost;
    int32 BackendPort;
    FString APIKey;

    // Real-time telemetry fan-out (UDP) to the telemetry-collector ??Firebase.
    FString CellId;

    double DemoRunStartedAtSeconds = 0.0;
    mutable double SimElapsedSeconds = 0.0;
    mutable double LastSimClockRealSeconds = 0.0;
    double SimTargetDurationSeconds = 0.0;
    int32 WebSocketConnectAttempts = 0;
    bool bRuntimeActorsInitialized = false;

    // An /agv/command awaiting arrival at its station anchor, keyed by AGV id so the
    // chat-correlated completion can be emitted when the AGV gets there.
    struct FPendingStationCommand
    {
        FString SessionId;
        FString CorrelationId;
        FString CommandId;
        FString CommandName;
        int32 StationId = 0;
    };
    TMap<FString, FPendingStationCommand> PendingStationCommands;

    TArray<TSharedPtr<FJsonObject>> TimelineEntries;
    TArray<TObjectPtr<AAGVActor>> SpawnedAgvs;
    UPROPERTY(Transient)
    TArray<TObjectPtr<UTransportOrder>> ActiveOrders;
    UPROPERTY(Transient)
    TArray<TObjectPtr<UTransportOrder>> CompletedOrders;
    UPROPERTY(Transient)
    TArray<TObjectPtr<ULoadObject>> ActiveLoads;
    TObjectPtr<ADispatcherActor> DispatcherActor = nullptr;
    TObjectPtr<ATrafficManagerActor> TrafficManager = nullptr;
    TObjectPtr<AIntersectionManager> IntersectionManager = nullptr;

    // F3 ??auto-directs the evaluator camera to collision/bottleneck hotspots.
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="VCORE|Cinematics", meta=(AllowPrivateAccess="true"))
    TObjectPtr<UCinematicEventDirector> CinematicDirector = nullptr;

    // F1 ??real-time congestion heatmap fed by live AGV positions.
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="VCORE|Visualization", meta=(AllowPrivateAccess="true"))
    TObjectPtr<UCongestionHeatmapComponent> CongestionHeatmap = nullptr;

    // F4 ??evaluates agent-supplied acceptance criteria into a PASS/FAIL verdict at run end.
    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="VCORE|Scenario", meta=(AllowPrivateAccess="true"))
    TObjectPtr<UScenarioVerificationComponent> ScenarioVerifier = nullptr;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="VCORE|Simulation", meta=(AllowPrivateAccess="true"))
    TObjectPtr<UKPIAccumulator> KPIAccumulator = nullptr;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="VCORE|Simulation", meta=(AllowPrivateAccess="true"))
    TObjectPtr<UAGVStationRegistryComponent> StationRegistry = nullptr;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="VCORE|Telemetry", meta=(AllowPrivateAccess="true"))
    TObjectPtr<UAGVTelemetryComponent> Telemetry = nullptr;

    // Floor rectangle (XY, world units) the heatmap grid maps over, centered on this controller.
    UPROPERTY(EditAnywhere, Category="VCORE|Visualization")
    FVector2D HeatmapFloorSize = FVector2D(4000.0f, 4000.0f);

    // Explicit camera targets for the web Zone buttons. Soft refs allow cameras to live in
    // a streaming level package while this controller lives in the persistent level.
    UPROPERTY(EditInstanceOnly, Category="VCORE|Camera")
    TSoftObjectPtr<AActor> Zone1CameraTarget;

    UPROPERTY(EditInstanceOnly, Category="VCORE|Camera")
    TSoftObjectPtr<AActor> Zone2CameraTarget;

    UPROPERTY(EditInstanceOnly, Category="VCORE|Camera")
    TSoftObjectPtr<AActor> Zone3CameraTarget;

    // Short ring buffer of human-readable recent events for the web HUD event ticker.
    TArray<FString> RecentHudEvents;
    void PushHudEvent(const FString& Line);

    // Last completed run's verdict, retained for the HUD after the run state resets.
    FString LastVerdictSummary;
    bool bLastVerdictPassed = true;

    TSharedPtr<IWebSocket> WebSocket;
    TSharedPtr<class IHttpRouter> HttpRouter;
    FHttpRouteHandle SimStartRouteHandle;
    FHttpRouteHandle SimStopRouteHandle;
    FHttpRouteHandle SimPauseRouteHandle;
    FHttpRouteHandle SimResumeRouteHandle;
    FHttpRouteHandle SimSpeedRouteHandle;
    FHttpRouteHandle AgvCommandRouteHandle;
    FHttpRouteHandle SimStatusRouteHandle;
    FHttpRouteHandle CameraSelectRouteHandle;
    FTimerHandle DemoAutoCompleteTimerHandle;
    FTimerHandle DemoProgressTimerHandle;
    FTimerHandle WebSocketRetryTimerHandle;
    FTimerHandle SimulationCompleteTimerHandle;
    FTimerHandle TelemetryTimerHandle;
    FTimerHandle AutoDispatchTimerHandle;
    // One-shot timers that launch each AGV AgvStartStaggerSeconds apart at sim start.
    TArray<FTimerHandle> StaggeredStartTimerHandles;

    // Assigns a delivery task to every idle/available AGV so the cell runs continuously
    // once the simulation starts. Driven by AutoDispatchTimerHandle.
    void DispatchIdleAgvs();

    // Per-frame pairwise proximity check between active AGVs. Complements the physics
    // overlap on CollisionComponent: SetActorLocation without sweep can miss cross-frame
    // collisions, so this guarantees detection regardless of frame rate or sim speed.
    void CheckAgvProximityCollisions();

    // True when a run is active and every spawned AGV is stopped on a collision — the signal
    // to terminate the run and report the collision halt to the backend.
    bool AllSpawnedAgvsCollisionStopped() const;

    // Sim event bus (USimEventBus) wiring. The controller is the sole subscriber that bridges
    // domain events to KPI/backend/cinematics; bound in BeginPlay, unbound in EndPlay so no stale
    // callbacks survive a PIE restart. Handlers carry the bodies of the former Emit*/Notify* calls.
    void BindSimEventBus();
    void UnbindSimEventBus();
    void HandleAgvStateChanged(const FSimAgvStateChangedEvent& Event);
    void HandleStationArrived(const FSimStationArrivedEvent& Event);
    void HandleTaskCompleted(const FSimTaskCompletedEvent& Event);
    void HandleCollision(const FSimCollisionEvent& Event);
    void HandleBottleneck(const FSimBottleneckEvent& Event);

    void LoadConfig();
    void StartHttpServer();
    void StopHttpServer();
    void ConnectWebSocket();
    void DisconnectWebSocket();
    void ScheduleWebSocketRetry();
    FString ResolveBackendWebSocketHost() const;
    void StartDemoFallback();
    void StopDemoFallback();
    void EmitInitialDemoEvents();
    void EmitProgressEvent();
    void CompleteDemoRun(const FString& StopReason);
    bool InitializeRuntimeSimulationActors();
    void DestroyRuntimeSimulationActors();
    bool StartRuntimeSimulation();
    void StopRuntimeSimulation();
    void CompleteRuntimeRun(const FString& StopReason);
    TSharedRef<FJsonObject> BuildRuntimeReport(const FString& StopReason) const;
    void ResetActiveRun();
    void ResetActiveRunForTeardown();
    void RecordTimelineEvent(const TSharedRef<FJsonObject>& EventJson);

    bool HandleSimStartRequest(const struct FHttpServerRequest& Request, const FHttpResultCallback& OnComplete);
    bool HandleSimStopRequest(const struct FHttpServerRequest& Request, const FHttpResultCallback& OnComplete);
    bool HandleSimPauseRequest(const struct FHttpServerRequest& Request, const FHttpResultCallback& OnComplete);
    bool HandleSimResumeRequest(const struct FHttpServerRequest& Request, const FHttpResultCallback& OnComplete);
    bool HandleSimSpeedRequest(const struct FHttpServerRequest& Request, const FHttpResultCallback& OnComplete);
    bool HandleAgvCommandRequest(const struct FHttpServerRequest& Request, const FHttpResultCallback& OnComplete);
    bool HandleSimStatusRequest(const struct FHttpServerRequest& Request, const FHttpResultCallback& OnComplete);
    bool HandleCameraSelectRequest(const struct FHttpServerRequest& Request, const FHttpResultCallback& OnComplete);

    // Per-AGV + aggregate telemetry, emitted as UDP datagrams to the collector.
    void EmitTelemetry();
    void SendTelemetryPayload(const TSharedRef<FJsonObject>& Json);
    void SelectViewTarget(const FString& AgvId);
    // Resolves a Process-level camera target for ZONE buttons by explicit reference, then fallback tag/name lookup.
    class AActor* FindZoneCamera(const FName& ZoneTag) const;
    bool RequestLoadConfiguredZoneCameraLevel(const FName& ZoneTag, const FString& AgvId);
    float ComputeProgressPercent() const;

    // Picks the AGV an /agv/command should drive using the dispatcher score model.
    AAGVActor* ResolveCommandAgv(const FString& AgvId, AStationActor* TargetStation, struct FDispatchScoreBreakdown* OutScore = nullptr) const;
    void RebuildStationRegistry();
    AStationActor* ResolveStation(int32 StationId) const;

    // Guarantees the autonomous loop has Pickup + Dropoff stations to interact with: if the level
    // authors neither kind, seeds a pair on each AGV path. Designer-authored stations take precedence.
    void EnsureInteractionStations();
    UTransportOrder* CreateStationCommandOrder(int32 StationId, const FString& LoadType, int32 Priority);
    void CompleteOrderForAgv(const FString& AgvId);

    // Posts a chat-correlated event back to the backend ingest webhook (/internal/ue5/events).
    void SendChatEvent(const FString& SessionId, const FString& CorrelationId, const FString& CommandId, const FString& EventType, const TSharedPtr<FJsonObject>& Payload);
    void ApplySimSpeed(float Multiplier);
    double UpdateSimClock() const;
    void RescheduleSimulationCompleteTimer();
    int32 GetActiveAgvCount() const;
    TSharedRef<FJsonObject> BuildStatusJson() const;

    static TSharedPtr<FJsonObject> ParseRequestBody(const struct FHttpServerRequest& Request);
    static void RespondJson(const FHttpResultCallback& OnComplete, const FString& Body);
};
