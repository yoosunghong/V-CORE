#include "AGVSimController.h"

#include "AGVActor.h"
#include "AGVPathActor.h"
#include "AGVStationRegistryComponent.h"
#include "AGVTelemetryComponent.h"
#include "CinematicEventDirector.h"
#include "CongestionHeatmapComponent.h"
#include "DispatcherActor.h"
#include "ScenarioVerificationComponent.h"
#include "SimEventBus.h"
#include "IntersectionManager.h"
#include "KPIAccumulator.h"
#include "LoadObject.h"
#include "StationActor.h"
#include "TrafficManagerActor.h"
#include "TransportOrder.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Components/SplineComponent.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/GameplayStatics.h"
#include "HttpModule.h"
#include "HttpServerModule.h"
#include "HttpServerResponse.h"
#include "Interfaces/IHttpResponse.h"
#include "IHttpRouter.h"
#include "IWebSocket.h"
#include "Async/Async.h"
#include "Math/UnrealMathUtility.h"
#include "Modules/ModuleManager.h"
#include "WebSocketsModule.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Misc/ConfigCacheIni.h"
#include "HAL/IConsoleManager.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

static constexpr int32 UE5_HTTP_PORT = 7777;
static constexpr double DEMO_MIN_REAL_DURATION_SEC = 2.0;
static constexpr double DEMO_MAX_REAL_DURATION_SEC = 10.0;
static constexpr double MAX_RUNTIME_REAL_DURATION_SEC = 120.0;

AAGVSimController::AAGVSimController()
{
    PrimaryActorTick.bCanEverTick = true;

    CinematicDirector = CreateDefaultSubobject<UCinematicEventDirector>(TEXT("CinematicDirector"));
    CongestionHeatmap = CreateDefaultSubobject<UCongestionHeatmapComponent>(TEXT("CongestionHeatmap"));
    KPIAccumulator = CreateDefaultSubobject<UKPIAccumulator>(TEXT("KPIAccumulator"));
    ScenarioVerifier = CreateDefaultSubobject<UScenarioVerificationComponent>(TEXT("ScenarioVerifier"));
    StationRegistry = CreateDefaultSubobject<UAGVStationRegistryComponent>(TEXT("StationRegistry"));
    Telemetry = CreateDefaultSubobject<UAGVTelemetryComponent>(TEXT("Telemetry"));

    CinematicDirector->bEditableWhenInherited = true;
    CongestionHeatmap->bEditableWhenInherited = true;
    ScenarioVerifier->bEditableWhenInherited = true;
}

namespace
{
    EScenarioMetric ParseScenarioMetric(const FString& Raw)
    {
        const FString Key = Raw.ToLower();
        if (Key == TEXT("avg_wait_sec") || Key == TEXT("avg_wait_time") || Key == TEXT("avg_wait")) return EScenarioMetric::AvgWaitSec;
        if (Key == TEXT("collision_count") || Key == TEXT("collisions") || Key == TEXT("collision")) return EScenarioMetric::CollisionCount;
        if (Key == TEXT("uptime_ratio") || Key == TEXT("uptime")) return EScenarioMetric::UptimeRatio;
        if (Key == TEXT("active_agvs") || Key == TEXT("active_agv")) return EScenarioMetric::ActiveAgvs;
        return EScenarioMetric::Throughput;
    }

    EScenarioCompare ParseScenarioCompare(const FString& Raw)
    {
        const FString Key = Raw.ToLower();
        if (Key == TEXT("<=") || Key == TEXT("lte") || Key == TEXT("le") || Key == TEXT("max")) return EScenarioCompare::LessOrEqual;
        if (Key == TEXT("==") || Key == TEXT("=") || Key == TEXT("eq") || Key == TEXT("equal")) return EScenarioCompare::Equal;
        return EScenarioCompare::GreaterOrEqual;
    }

    // Parses the agent's optional "acceptance" array (boundary ??typed checks). Each entry is
    // {metric, comparator, threshold, label?}; malformed entries are skipped.
    TArray<FScenarioCheck> ParseAcceptanceChecks(const TSharedPtr<FJsonObject>& ParamsObj)
    {
        TArray<FScenarioCheck> Checks;
        if (!ParamsObj.IsValid())
        {
            return Checks;
        }
        const TArray<TSharedPtr<FJsonValue>>* Array = nullptr;
        if (!ParamsObj->TryGetArrayField(TEXT("acceptance"), Array) || Array == nullptr)
        {
            return Checks;
        }
        for (const TSharedPtr<FJsonValue>& Value : *Array)
        {
            const TSharedPtr<FJsonObject>* Entry = nullptr;
            if (!Value.IsValid() || !Value->TryGetObject(Entry) || Entry == nullptr)
            {
                continue;
            }
            double Threshold = 0.0;
            if (!(*Entry)->TryGetNumberField(TEXT("threshold"), Threshold))
            {
                continue;
            }
            FScenarioCheck Check;
            Check.Metric = ParseScenarioMetric((*Entry)->HasField(TEXT("metric")) ? (*Entry)->GetStringField(TEXT("metric")) : FString());
            Check.Comparator = ParseScenarioCompare((*Entry)->HasField(TEXT("comparator")) ? (*Entry)->GetStringField(TEXT("comparator")) : FString());
            Check.Threshold = static_cast<float>(Threshold);
            Check.Label = (*Entry)->HasField(TEXT("label")) ? (*Entry)->GetStringField(TEXT("label")) : FString();
            Checks.Add(MoveTemp(Check));
        }
        return Checks;
    }
}

void AAGVSimController::BeginPlay()
{
    Super::BeginPlay();
    LoadConfig();
    if (Telemetry)
    {
        Telemetry->SetupSocket();
    }
    StartHttpServer();
    RegisterDebugConsoleCommands();
    BindSimEventBus();

    // F3 ??blend back to the controller (cell overview) when a cinematic cut finishes.
    if (CinematicDirector)
    {
        CinematicDirector->SetOverviewTarget(this);
    }
}

void AAGVSimController::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
    UnbindSimEventBus();
    UnregisterDebugConsoleCommands();
    ResetActiveRunForTeardown();
    StopHttpServer();
    if (Telemetry)
    {
        Telemetry->TeardownSocket();
    }
    Super::EndPlay(EndPlayReason);
}

void AAGVSimController::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);

    if (bSimRunning && !bSimPaused && bRuntimeActorsInitialized)
    {
        CheckAgvProximityCollisions();
    }
}

void AAGVSimController::LoadConfig()
{
    // Reads from Config/DefaultGame.ini [AGVSim] section.  TODO: config
    GConfig->GetString(TEXT("AGVSim"), TEXT("BackendHost"), BackendHost, GGameIni);
    GConfig->GetInt(TEXT("AGVSim"), TEXT("BackendPort"), BackendPort, GGameIni);
    GConfig->GetString(TEXT("AGVSim"), TEXT("APIKey"), APIKey, GGameIni);

    if (BackendHost.IsEmpty()) BackendHost = TEXT("localhost");
    if (BackendPort == 0) BackendPort = 8000;
    if (APIKey.IsEmpty()) APIKey = TEXT("demo-api-key-change-in-prod");

    FAGVTelemetrySettings TelemetrySettings;
    GConfig->GetString(TEXT("AGVSim"), TEXT("TelemetryHost"), TelemetrySettings.Host, GGameIni);
    GConfig->GetString(TEXT("AGVSim"), TEXT("TelemetryTransport"), TelemetrySettings.Transport, GGameIni);
    GConfig->GetInt(TEXT("AGVSim"), TEXT("TelemetryUdpPort"), TelemetrySettings.UdpPort, GGameIni);
    GConfig->GetInt(TEXT("AGVSim"), TEXT("TelemetryTcpPort"), TelemetrySettings.TcpPort, GGameIni);
    GConfig->GetString(TEXT("AGVSim"), TEXT("CellId"), TelemetrySettings.CellId, GGameIni);

    if (TelemetrySettings.Host.IsEmpty()) TelemetrySettings.Host = TEXT("127.0.0.1");
    if (TelemetrySettings.Transport.IsEmpty()) TelemetrySettings.Transport = TEXT("tcp");
    if (TelemetrySettings.UdpPort == 0) TelemetrySettings.UdpPort = 9999;
    if (TelemetrySettings.TcpPort == 0) TelemetrySettings.TcpPort = 9998;
    if (TelemetrySettings.CellId.IsEmpty()) TelemetrySettings.CellId = TEXT("cell_demo");
    CellId = TelemetrySettings.CellId;
    if (Telemetry)
    {
        Telemetry->Configure(TelemetrySettings);
    }
}

void AAGVSimController::StartHttpServer()
{
    FHttpServerModule& HttpServer = FHttpServerModule::Get();
    HttpRouter = HttpServer.GetHttpRouter(UE5_HTTP_PORT);
    if (!HttpRouter.IsValid())
    {
        UE_LOG(LogTemp, Warning, TEXT("AGVSimController: Failed to acquire HTTP router on port %d"), UE5_HTTP_PORT);
        return;
    }

    SimStartRouteHandle = HttpRouter->BindRoute(
        FHttpPath(TEXT("/sim/start")),
        EHttpServerRequestVerbs::VERB_POST,
        FHttpRequestHandler::CreateLambda(
            [this](const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete) -> bool
            {
                return HandleSimStartRequest(Request, OnComplete);
            }
        )
    );
    SimStopRouteHandle = HttpRouter->BindRoute(
        FHttpPath(TEXT("/sim/stop")),
        EHttpServerRequestVerbs::VERB_POST,
        FHttpRequestHandler::CreateLambda(
            [this](const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete) -> bool
            {
                return HandleSimStopRequest(Request, OnComplete);
            }
        )
    );
    SimPauseRouteHandle = HttpRouter->BindRoute(
        FHttpPath(TEXT("/sim/pause")),
        EHttpServerRequestVerbs::VERB_POST,
        FHttpRequestHandler::CreateLambda(
            [this](const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete) -> bool
            {
                return HandleSimPauseRequest(Request, OnComplete);
            }
        )
    );
    SimResumeRouteHandle = HttpRouter->BindRoute(
        FHttpPath(TEXT("/sim/resume")),
        EHttpServerRequestVerbs::VERB_POST,
        FHttpRequestHandler::CreateLambda(
            [this](const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete) -> bool
            {
                return HandleSimResumeRequest(Request, OnComplete);
            }
        )
    );
    SimSpeedRouteHandle = HttpRouter->BindRoute(
        FHttpPath(TEXT("/sim/speed")),
        EHttpServerRequestVerbs::VERB_POST,
        FHttpRequestHandler::CreateLambda(
            [this](const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete) -> bool
            {
                return HandleSimSpeedRequest(Request, OnComplete);
            }
        )
    );
    AgvCommandRouteHandle = HttpRouter->BindRoute(
        FHttpPath(TEXT("/agv/command")),
        EHttpServerRequestVerbs::VERB_POST,
        FHttpRequestHandler::CreateLambda(
            [this](const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete) -> bool
            {
                return HandleAgvCommandRequest(Request, OnComplete);
            }
        )
    );
    SimStatusRouteHandle = HttpRouter->BindRoute(
        FHttpPath(TEXT("/sim/status")),
        EHttpServerRequestVerbs::VERB_GET,
        FHttpRequestHandler::CreateLambda(
            [this](const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete) -> bool
            {
                return HandleSimStatusRequest(Request, OnComplete);
            }
        )
    );
    CameraSelectRouteHandle = HttpRouter->BindRoute(
        FHttpPath(TEXT("/camera/select")),
        EHttpServerRequestVerbs::VERB_POST,
        FHttpRequestHandler::CreateLambda(
            [this](const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete) -> bool
            {
                return HandleCameraSelectRequest(Request, OnComplete);
            }
        )
    );

    HttpServer.StartAllListeners();
    UE_LOG(LogTemp, Log, TEXT("AGVSimController: HTTP server listening on port %d"), UE5_HTTP_PORT);
}

void AAGVSimController::StopHttpServer()
{
    if (HttpRouter.IsValid())
    {
        if (SimStartRouteHandle.IsValid())
        {
            HttpRouter->UnbindRoute(SimStartRouteHandle);
            SimStartRouteHandle.Reset();
        }

        if (SimStopRouteHandle.IsValid())
        {
            HttpRouter->UnbindRoute(SimStopRouteHandle);
            SimStopRouteHandle.Reset();
        }

        auto UnbindIfValid = [this](FHttpRouteHandle& Handle)
        {
            if (Handle.IsValid())
            {
                HttpRouter->UnbindRoute(Handle);
                Handle.Reset();
            }
        };
        UnbindIfValid(SimPauseRouteHandle);
        UnbindIfValid(SimResumeRouteHandle);
        UnbindIfValid(SimSpeedRouteHandle);
        UnbindIfValid(AgvCommandRouteHandle);
        UnbindIfValid(SimStatusRouteHandle);
        UnbindIfValid(CameraSelectRouteHandle);
    }

    HttpRouter.Reset();
    FHttpServerModule::Get().StopAllListeners();
}

bool AAGVSimController::HandleSimStartRequest(
    const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete)
{
    TSharedPtr<FJsonObject> Json = ParseRequestBody(Request);
    if (!Json.IsValid())
    {
        auto Response = FHttpServerResponse::Error(EHttpServerResponseCodes::BadRequest, TEXT(""), TEXT("Invalid JSON"));
        OnComplete(MoveTemp(Response));
        return true;
    }

    // The agent-driven payload nests sim params under "parameters" and carries chat
    // correlation ids; legacy callers used a flat body with run_id. Support both.
    const TSharedPtr<FJsonObject>* ParamsObjPtr = nullptr;
    Json->TryGetObjectField(TEXT("parameters"), ParamsObjPtr);
    const TSharedPtr<FJsonObject> ParamsObj = (ParamsObjPtr && ParamsObjPtr->IsValid()) ? *ParamsObjPtr : Json;

    const FString SessionId = Json->HasField(TEXT("session_id")) ? Json->GetStringField(TEXT("session_id")) : FString();
    const FString CorrelationId = Json->HasField(TEXT("correlation_id")) ? Json->GetStringField(TEXT("correlation_id")) : FString();
    const FString CommandId = Json->HasField(TEXT("command_id")) ? Json->GetStringField(TEXT("command_id")) : FString();

    FSimStartParams RequestedParams;
    RequestedParams.RunId = Json->HasField(TEXT("run_id")) ? Json->GetStringField(TEXT("run_id")) : CommandId;
    if (RequestedParams.RunId.IsEmpty()) RequestedParams.RunId = FGuid::NewGuid().ToString(EGuidFormats::DigitsWithHyphens);
    double NumberValue = 0.0;
    RequestedParams.Speed = ParamsObj->TryGetNumberField(TEXT("speed_multiplier"), NumberValue) ? static_cast<float>(NumberValue)
        : (ParamsObj->TryGetNumberField(TEXT("speed"), NumberValue) ? static_cast<float>(NumberValue) : 1.0f);
    RequestedParams.Duration = ParamsObj->TryGetNumberField(TEXT("duration"), NumberValue) ? static_cast<int32>(NumberValue) : 3600;
    RequestedParams.PolicyId = ParamsObj->HasField(TEXT("policy_id")) ? ParamsObj->GetStringField(TEXT("policy_id")) : TEXT("POLICY_FIFO");
    RequestedParams.AgvCount = ParamsObj->TryGetNumberField(TEXT("agv_count"), NumberValue) ? static_cast<int32>(NumberValue) : 3;
    RequestedParams.BottleneckThresholdSec = ParamsObj->TryGetNumberField(TEXT("bottleneck_threshold_sec"), NumberValue) ? static_cast<float>(NumberValue) : 10.0f;

    // F4 ??optional agent-supplied acceptance criteria evaluated into a verdict at run end.
    const TArray<FScenarioCheck> AcceptanceChecks = ParseAcceptanceChecks(ParamsObj);

    AAGVSimController* Controller = this;
    AsyncTask(ENamedThreads::GameThread, [Controller, RequestedParams, SessionId, CorrelationId, CommandId, AcceptanceChecks]()
    {
        if (!IsValid(Controller))
        {
            return;
        }

        if (Controller->bSimRunning)
        {
            UE_LOG(LogTemp, Warning, TEXT("AGVSimController: Ignoring start request for run %s because a simulation is already running"), *RequestedParams.RunId);
            return;
        }

        Controller->ActiveSessionId = SessionId;
        Controller->ActiveCorrelationId = CorrelationId;
        Controller->ActiveCommandId = CommandId;
        Controller->bSimPaused = false;
        Controller->SpeedMultiplier = FMath::Max(RequestedParams.Speed, 0.1f);
        Controller->ApplySimSpeed(Controller->SpeedMultiplier);
        Controller->bSimRunning = true;
        Controller->ActiveParams = RequestedParams;
        if (Controller->ScenarioVerifier)
        {
            Controller->ScenarioVerifier->LoadChecks(AcceptanceChecks);
        }
        Controller->LastVerdictSummary.Reset();
        Controller->bLastVerdictPassed = true;
        Controller->KPIAccumulator->Reset();
        Controller->TimelineEntries.Reset();
        Controller->DemoRunStartedAtSeconds = FPlatformTime::Seconds();
        Controller->SimElapsedSeconds = 0.0;
        Controller->LastSimClockRealSeconds = Controller->DemoRunStartedAtSeconds;
        Controller->SimTargetDurationSeconds = 0.0;
        Controller->WebSocketConnectAttempts = 0;

        Controller->ConnectWebSocket();

        if (!Controller->StartRuntimeSimulation())
        {
            UE_LOG(LogTemp, Warning, TEXT("AGVSimController: Runtime simulation startup failed, falling back to placeholder flow"));
            Controller->StartDemoFallback();
        }
    });

    FString ResponseBody = FString::Printf(TEXT("{\"status\":\"accepted\",\"run_id\":\"%s\"}"), *RequestedParams.RunId);
    FTCHARToUTF8 Converted(*ResponseBody);
    TArray<uint8> ResponseBytes;
    ResponseBytes.Append(reinterpret_cast<const uint8*>(Converted.Get()), Converted.Length());

    auto Response = FHttpServerResponse::Create(ResponseBytes, TEXT("application/json"));
    OnComplete(MoveTemp(Response));
    return true;
}

bool AAGVSimController::HandleSimStopRequest(
    const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete)
{
    FString RequestedRunId;
    if (TSharedPtr<FJsonObject> Json = ParseRequestBody(Request);
        Json.IsValid() && Json->HasTypedField<EJson::String>(TEXT("run_id")))
    {
        RequestedRunId = Json->GetStringField(TEXT("run_id"));
    }

    AAGVSimController* Controller = this;
    AsyncTask(ENamedThreads::GameThread, [Controller, RequestedRunId]()
    {
        if (!IsValid(Controller))
        {
            return;
        }

        if (!Controller->bSimRunning)
        {
            return;
        }

        if (!RequestedRunId.IsEmpty() && RequestedRunId != Controller->ActiveParams.RunId)
        {
            UE_LOG(LogTemp, Warning, TEXT("AGVSimController: Ignoring stop request for run %s because active run is %s"), *RequestedRunId, *Controller->ActiveParams.RunId);
            return;
        }

        if (Controller->bRuntimeActorsInitialized)
        {
            Controller->CompleteRuntimeRun(TEXT("STOP_COMMAND"));
        }
        else
        {
            Controller->CompleteDemoRun(TEXT("STOP_COMMAND"));
        }
    });

    const FString ResponseRunId = RequestedRunId.IsEmpty() ? TEXT("pending-active-run") : RequestedRunId;
    FString ResponseBody = FString::Printf(TEXT("{\"status\":\"accepted\",\"run_id\":\"%s\"}"), *ResponseRunId);
    FTCHARToUTF8 Converted(*ResponseBody);
    TArray<uint8> ResponseBytes;
    ResponseBytes.Append(reinterpret_cast<const uint8*>(Converted.Get()), Converted.Length());

    auto Response = FHttpServerResponse::Create(ResponseBytes, TEXT("application/json"));
    OnComplete(MoveTemp(Response));
    return true;
}

void AAGVSimController::ConnectWebSocket()
{
    if (!bSimRunning || ActiveParams.RunId.IsEmpty())
    {
        return;
    }

    UWorld* World = GetWorld();
    if (World)
    {
        World->GetTimerManager().ClearTimer(WebSocketRetryTimerHandle);
    }

    DisconnectWebSocket();
    ++WebSocketConnectAttempts;

    const FString ResolvedBackendHost = ResolveBackendWebSocketHost();
    const FString WsUrl = FString::Printf(TEXT("ws://%s:%d/internal/ue5/stream"), *ResolvedBackendHost, BackendPort);

    TMap<FString, FString> Headers;
    Headers.Add(TEXT("X-AGV-API-Key"), APIKey);

    UE_LOG(LogTemp, Log, TEXT("AGVSimController: Connecting WebSocket to %s (attempt %d/%d)"), *WsUrl, WebSocketConnectAttempts, MaxWebSocketConnectRetries);

    FModuleManager::LoadModuleChecked<FWebSocketsModule>(TEXT("WebSockets"));
    WebSocket = FWebSocketsModule::Get().CreateWebSocket(WsUrl, TEXT("ws"), Headers);

    WebSocket->OnConnected().AddLambda([this]()
    {
        WebSocketConnectAttempts = 0;
        UE_LOG(LogTemp, Log, TEXT("AGVSimController: WebSocket connected to backend"));
        if (!bRuntimeActorsInitialized)
        {
            EmitInitialDemoEvents();
        }
    });

    WebSocket->OnConnectionError().AddLambda([this](const FString& Error)
    {
        UE_LOG(LogTemp, Warning, TEXT("AGVSimController: WebSocket error: %s"), *Error);
        ScheduleWebSocketRetry();
    });

    WebSocket->OnClosed().AddLambda([this](int32 Code, const FString& Reason, bool bClean)
    {
        UE_LOG(LogTemp, Log, TEXT("AGVSimController: WebSocket closed (%d): %s"), Code, *Reason);
        if (!bClean && bSimRunning)
        {
            ScheduleWebSocketRetry();
        }
    });

    WebSocket->Connect();
}

void AAGVSimController::DisconnectWebSocket()
{
    if (UWorld* World = GetWorld())
    {
        World->GetTimerManager().ClearTimer(WebSocketRetryTimerHandle);
    }

    if (WebSocket.IsValid() && WebSocket->IsConnected())
    {
        WebSocket->Close();
    }
    WebSocket.Reset();
}

void AAGVSimController::ScheduleWebSocketRetry()
{
    if (!bSimRunning || WebSocketConnectAttempts >= MaxWebSocketConnectRetries)
    {
        return;
    }

    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }

    constexpr float RetryDelaySeconds = 2.0f;
    World->GetTimerManager().SetTimer(WebSocketRetryTimerHandle, this, &AAGVSimController::ConnectWebSocket, RetryDelaySeconds, false);
}

FString AAGVSimController::ResolveBackendWebSocketHost() const
{
    if (BackendHost.Equals(TEXT("localhost"), ESearchCase::IgnoreCase))
    {
        return TEXT("127.0.0.1");
    }

    return BackendHost;
}

void AAGVSimController::SendSimEvent(const TSharedRef<FJsonObject>& EventJson)
{
    RecordTimelineEvent(EventJson);
    if (!WebSocket.IsValid() || !WebSocket->IsConnected() || ActiveSessionId.IsEmpty())
    {
        return;
    }

    TSharedRef<FJsonObject> EnvelopeJson = MakeShared<FJsonObject>();
    EnvelopeJson->SetStringField(TEXT("session_id"), ActiveSessionId);
    EnvelopeJson->SetStringField(TEXT("correlation_id"), ActiveCorrelationId.IsEmpty() ? ActiveSessionId : ActiveCorrelationId);
    EnvelopeJson->SetStringField(TEXT("command_id"), ActiveCommandId);
    EnvelopeJson->SetStringField(TEXT("event_type"), TEXT("sim.event"));
    EnvelopeJson->SetObjectField(TEXT("payload"), EventJson);

    FString Message;
    TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Message);
    FJsonSerializer::Serialize(EnvelopeJson, Writer);
    WebSocket->Send(Message);
}

void AAGVSimController::SendSimComplete(const TSharedRef<FJsonObject>& ReportJson)
{
    // The Virtual Process backend completes the agent command via the chat-event
    // ingest webhook (no KPI-complete endpoint). Forward the KPIs + stop reason as a
    // chat-correlated completion event so the originating chat session gets a report.
    if (!ActiveSessionId.IsEmpty() && !ActiveCommandId.IsEmpty())
    {
        TSharedPtr<FJsonObject> Payload = MakeShared<FJsonObject>();
        Payload->SetStringField(TEXT("run_id"), ActiveParams.RunId);
        if (ReportJson->HasTypedField<EJson::String>(TEXT("stop_reason")))
        {
            Payload->SetStringField(TEXT("stop_reason"), ReportJson->GetStringField(TEXT("stop_reason")));
        }
        if (ReportJson->HasTypedField<EJson::Object>(TEXT("kpis")))
        {
            Payload->SetObjectField(TEXT("kpis"), ReportJson->GetObjectField(TEXT("kpis")));
        }
        // F4 ??forward the acceptance verdict so the agent can report PASS/FAIL in chat.
        if (ReportJson->HasTypedField<EJson::Object>(TEXT("verdict")))
        {
            Payload->SetObjectField(TEXT("verdict"), ReportJson->GetObjectField(TEXT("verdict")));
        }
        SendChatEvent(ActiveSessionId, ActiveCorrelationId, ActiveCommandId, TEXT("robot.command.completed"), Payload);
    }

    // F4 ??retain a short verdict line for the in-viewport HUD (survives the run reset below).
    if (ReportJson->HasTypedField<EJson::Object>(TEXT("verdict")))
    {
        const TSharedPtr<FJsonObject> VerdictJson = ReportJson->GetObjectField(TEXT("verdict"));
        bLastVerdictPassed = VerdictJson->HasField(TEXT("passed")) && VerdictJson->GetBoolField(TEXT("passed"));
        const int32 Total = VerdictJson->HasField(TEXT("checks_total")) ? static_cast<int32>(VerdictJson->GetNumberField(TEXT("checks_total"))) : 0;
        int32 PassedCount = 0;
        const TArray<TSharedPtr<FJsonValue>>* PassedArray = nullptr;
        if (VerdictJson->TryGetArrayField(TEXT("passed_labels"), PassedArray) && PassedArray)
        {
            PassedCount = PassedArray->Num();
        }
        LastVerdictSummary = FString::Printf(TEXT("%s  (%d/%d criteria)"),
            bLastVerdictPassed ? TEXT("PASS") : TEXT("FAIL"), PassedCount, Total);
    }

    ApplySimSpeed(1.0f);
    ResetActiveRun();
}

double AAGVSimController::GetSimTimestampSeconds() const
{
    return UpdateSimClock();
}

double AAGVSimController::UpdateSimClock() const
{
    if (!bSimRunning || LastSimClockRealSeconds <= 0.0)
    {
        return 0.0;
    }

    if (!bSimPaused)
    {
        const double Now = FPlatformTime::Seconds();
        const double DeltaRealSeconds = FMath::Max(Now - LastSimClockRealSeconds, 0.0);
        SimElapsedSeconds += DeltaRealSeconds * FMath::Max(static_cast<double>(SpeedMultiplier), 0.1);
        LastSimClockRealSeconds = Now;
    }
    return SimElapsedSeconds;
}

void AAGVSimController::RescheduleSimulationCompleteTimer()
{
    UWorld* World = GetWorld();
    if (!World || !bSimRunning)
    {
        return;
    }

    World->GetTimerManager().ClearTimer(SimulationCompleteTimerHandle);
    const double EffectiveSpeed = FMath::Max(static_cast<double>(SpeedMultiplier), 0.1);
    if (SimTargetDurationSeconds <= 0.0)
    {
        const double InitialRealDuration = FMath::Clamp(static_cast<double>(ActiveParams.Duration) / EffectiveSpeed, DEMO_MIN_REAL_DURATION_SEC, MAX_RUNTIME_REAL_DURATION_SEC);
        SimTargetDurationSeconds = InitialRealDuration * EffectiveSpeed;
    }
    const double RemainingSimSeconds = FMath::Max(SimTargetDurationSeconds - UpdateSimClock(), 0.0);
    // ApplySimSpeed sets global time dilation = SpeedMultiplier, so the timer manager already
    // ticks SpeedMultiplier× faster. The delay must therefore be expressed in *simulated*
    // seconds ??dividing by speed here double-counts and fires the timer at 1/speed of the
    // intended progress (e.g. completing a 4× run at 25%). SimElapsedSeconds (real × speed) and
    // the dilated timer both advance at the same rate, so this lands exactly at 100%.
    const float RemainingTimerSeconds = static_cast<float>(FMath::Max(RemainingSimSeconds, 0.05));
    World->GetTimerManager().SetTimer(
        SimulationCompleteTimerHandle,
        FTimerDelegate::CreateLambda([this]()
        {
            CompleteRuntimeRun(TEXT("TIMER_EXPIRED"));
        }),
        RemainingTimerSeconds,
        false);
}

void AAGVSimController::BindSimEventBus()
{
    if (USimEventBus* Bus = USimEventBus::Get(this))
    {
        Bus->OnAgvStateChanged.AddUObject(this, &AAGVSimController::HandleAgvStateChanged);
        Bus->OnStationArrived.AddUObject(this, &AAGVSimController::HandleStationArrived);
        Bus->OnTaskCompleted.AddUObject(this, &AAGVSimController::HandleTaskCompleted);
        Bus->OnCollision.AddUObject(this, &AAGVSimController::HandleCollision);
        Bus->OnBottleneck.AddUObject(this, &AAGVSimController::HandleBottleneck);
    }
}

void AAGVSimController::UnbindSimEventBus()
{
    if (USimEventBus* Bus = USimEventBus::Get(this))
    {
        Bus->OnAgvStateChanged.RemoveAll(this);
        Bus->OnStationArrived.RemoveAll(this);
        Bus->OnTaskCompleted.RemoveAll(this);
        Bus->OnCollision.RemoveAll(this);
        Bus->OnBottleneck.RemoveAll(this);
    }
}

void AAGVSimController::HandleTaskCompleted(const FSimTaskCompletedEvent& Event)
{
    const FString& AgvId = Event.AgvId;
    const double TaskDurationSec = Event.TaskDurationSec;

    const int32 CompletedTaskCount = KPIAccumulator->RecordTaskCompleted();

    TSharedRef<FJsonObject> EventJson = MakeShared<FJsonObject>();
    EventJson->SetStringField(TEXT("type"), TEXT("SimEvent"));
    EventJson->SetStringField(TEXT("run_id"), ActiveParams.RunId);
    EventJson->SetNumberField(TEXT("sim_timestamp"), GetSimTimestampSeconds());
    EventJson->SetStringField(TEXT("event_type"), TEXT("TASK_COMPLETE"));
    EventJson->SetStringField(TEXT("agv_id"), AgvId);

    TSharedPtr<FJsonObject> DataJson = MakeShared<FJsonObject>();
    DataJson->SetStringField(TEXT("task_id"), FString::Printf(TEXT("%s-TASK-%d"), *AgvId, CompletedTaskCount));
    DataJson->SetStringField(TEXT("task_type"), TEXT("DELIVERY"));
    DataJson->SetNumberField(TEXT("duration_sec"), TaskDurationSec);
    DataJson->SetStringField(TEXT("agv_id"), AgvId);
    EventJson->SetObjectField(TEXT("data"), DataJson);

    SendSimEvent(EventJson);
}

void AAGVSimController::HandleCollision(const FSimCollisionEvent& Event)
{
    const FString& AgvIdA = Event.AgvIdA;
    const FString& AgvIdB = Event.AgvIdB;
    const FVector& Position = Event.Position;
    const float RelativeVelocity = Event.RelativeVelocity;

    KPIAccumulator->RecordCollision();

    TSharedRef<FJsonObject> EventJson = MakeShared<FJsonObject>();
    EventJson->SetStringField(TEXT("type"), TEXT("SimEvent"));
    EventJson->SetStringField(TEXT("run_id"), ActiveParams.RunId);
    EventJson->SetNumberField(TEXT("sim_timestamp"), GetSimTimestampSeconds());
    EventJson->SetStringField(TEXT("event_type"), TEXT("COLLISION"));

    TSharedPtr<FJsonObject> DataJson = MakeShared<FJsonObject>();
    DataJson->SetStringField(TEXT("agv_id_a"), AgvIdA);
    DataJson->SetStringField(TEXT("agv_id_b"), AgvIdB);
    DataJson->SetNumberField(TEXT("relative_velocity"), RelativeVelocity);

    TSharedPtr<FJsonObject> PositionJson = MakeShared<FJsonObject>();
    PositionJson->SetNumberField(TEXT("x"), Position.X);
    PositionJson->SetNumberField(TEXT("y"), Position.Y);
    PositionJson->SetNumberField(TEXT("z"), Position.Z);
    DataJson->SetObjectField(TEXT("position"), PositionJson);
    EventJson->SetObjectField(TEXT("data"), DataJson);

    SendSimEvent(EventJson);

    PushHudEvent(FString::Printf(TEXT("COLLISION  %s x %s"), *AgvIdA, *AgvIdB));

    // F3 ??auto-cut the evaluator camera to the collision.
    if (CinematicDirector)
    {
        CinematicDirector->FocusOnEvent(ECinematicEventKind::Collision, Position, nullptr);
    }
}

void AAGVSimController::HandleAgvStateChanged(const FSimAgvStateChangedEvent& Event)
{
    const FString& AgvId = Event.AgvId;
    const FString& FromState = Event.FromState;
    const FString& ToState = Event.ToState;
    const float CurrentSpeed = Event.Speed;
    const float Battery = Event.Battery;

    TSharedRef<FJsonObject> EventJson = MakeShared<FJsonObject>();
    EventJson->SetStringField(TEXT("type"), TEXT("SimEvent"));
    EventJson->SetStringField(TEXT("run_id"), ActiveParams.RunId);
    EventJson->SetNumberField(TEXT("sim_timestamp"), GetSimTimestampSeconds());
    EventJson->SetStringField(TEXT("event_type"), TEXT("AGV_STATE_CHANGE"));
    EventJson->SetStringField(TEXT("agv_id"), AgvId);

    TSharedPtr<FJsonObject> DataJson = MakeShared<FJsonObject>();
    DataJson->SetStringField(TEXT("from_state"), FromState);
    DataJson->SetStringField(TEXT("to_state"), ToState);
    DataJson->SetNumberField(TEXT("speed"), CurrentSpeed);
    DataJson->SetNumberField(TEXT("battery"), Battery);
    EventJson->SetObjectField(TEXT("data"), DataJson);

    SendSimEvent(EventJson);
}

void AAGVSimController::HandleStationArrived(const FSimStationArrivedEvent& Event)
{
    PushHudEvent(FString::Printf(TEXT("ARRIVE %s @ St%d (%s)"), *Event.AgvId, Event.StationId, *Event.StationKind));
}

void AAGVSimController::HandleBottleneck(const FSimBottleneckEvent& Event)
{
    const FString& AgvId = Event.AgvId;
    const FString& SectionId = Event.SectionId;
    const double WaitDurationSec = Event.WaitDurationSec;
    const TArray<FString>& QueuedAgvIds = Event.QueuedAgvIds;

    TSharedRef<FJsonObject> EventJson = MakeShared<FJsonObject>();
    EventJson->SetStringField(TEXT("type"), TEXT("SimEvent"));
    EventJson->SetStringField(TEXT("run_id"), ActiveParams.RunId);
    EventJson->SetNumberField(TEXT("sim_timestamp"), GetSimTimestampSeconds());
    EventJson->SetStringField(TEXT("event_type"), TEXT("BOTTLENECK"));
    EventJson->SetStringField(TEXT("agv_id"), AgvId);

    TSharedPtr<FJsonObject> DataJson = MakeShared<FJsonObject>();
    DataJson->SetStringField(TEXT("section_id"), SectionId);
    DataJson->SetNumberField(TEXT("wait_duration_sec"), WaitDurationSec);

    TArray<TSharedPtr<FJsonValue>> QueueJson;
    for (const FString& QueuedAgvId : QueuedAgvIds)
    {
        QueueJson.Add(MakeShared<FJsonValueString>(QueuedAgvId));
    }

    DataJson->SetArrayField(TEXT("queued_agv_ids"), QueueJson);
    EventJson->SetObjectField(TEXT("data"), DataJson);

    SendSimEvent(EventJson);

    PushHudEvent(FString::Printf(TEXT("BOTTLENECK %s @ %s (%.0fs)"), *AgvId, *SectionId, WaitDurationSec));

    // F3 ??auto-cut the evaluator camera to the bottlenecked AGV's location.
    if (CinematicDirector)
    {
        for (AAGVActor* Agv : SpawnedAgvs)
        {
            if (IsValid(Agv) && Agv->GetAgvId().Equals(AgvId, ESearchCase::IgnoreCase))
            {
                CinematicDirector->FocusOnEvent(ECinematicEventKind::Bottleneck, Agv->GetActorLocation(), Agv);
                break;
            }
        }
    }
}

int32 AAGVSimController::GetTotalTasksCompleted() const
{
    return KPIAccumulator ? KPIAccumulator->GetTotalTasksCompleted() : 0;
}

void AAGVSimController::PushHudEvent(const FString& Line)
{
    RecentHudEvents.Add(Line);
    constexpr int32 MaxHudEvents = 5;
    while (RecentHudEvents.Num() > MaxHudEvents)
    {
        RecentHudEvents.RemoveAt(0);
    }
}

FVcoreHudSnapshot AAGVSimController::GetHudSnapshot() const
{
    FVcoreHudSnapshot Snapshot;
    Snapshot.bRunning = bSimRunning;
    Snapshot.bPaused = bSimPaused;
    Snapshot.Speed = SpeedMultiplier;
    Snapshot.ProgressPercent = ComputeProgressPercent();
    Snapshot.TasksCompleted = KPIAccumulator ? KPIAccumulator->GetTotalTasksCompleted() : 0;
    Snapshot.Collisions = KPIAccumulator ? KPIAccumulator->GetCollisionEvents() : 0;
    Snapshot.PolicyId = ActiveParams.PolicyId;
    Snapshot.RecentEvents = RecentHudEvents;
    Snapshot.VerdictSummary = LastVerdictSummary;
    Snapshot.bVerdictPassed = bLastVerdictPassed;
    return Snapshot;
}

void AAGVSimController::StartDemoFallback()
{
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }

    const double EffectiveSpeed = FMath::Max(ActiveParams.Speed, 1.0f);
    const double SimulatedRealDuration = static_cast<double>(ActiveParams.Duration) / EffectiveSpeed;
    const float AutoCompleteDelay = static_cast<float>(FMath::Clamp(SimulatedRealDuration, DEMO_MIN_REAL_DURATION_SEC, DEMO_MAX_REAL_DURATION_SEC));
    SimTargetDurationSeconds = static_cast<double>(AutoCompleteDelay) * EffectiveSpeed;

    World->GetTimerManager().SetTimer(DemoProgressTimerHandle, this, &AAGVSimController::EmitProgressEvent, 1.0f, true, 1.0f);
    // The timer manager runs on dilated world time (global time dilation = speed), so the
    // auto-complete delay is expressed in simulated seconds (= AutoCompleteDelay × speed); it
    // still elapses after AutoCompleteDelay real seconds but lets the HUD reach 100%.
    World->GetTimerManager().SetTimer(
        DemoAutoCompleteTimerHandle,
        FTimerDelegate::CreateLambda([this]()
        {
            CompleteDemoRun(TEXT("TIMER_EXPIRED"));
        }),
        static_cast<float>(SimTargetDurationSeconds),
        false);
}

void AAGVSimController::StopDemoFallback()
{
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }

    World->GetTimerManager().ClearTimer(DemoProgressTimerHandle);
    World->GetTimerManager().ClearTimer(DemoAutoCompleteTimerHandle);
}

void AAGVSimController::EmitInitialDemoEvents()
{
    if (!bSimRunning)
    {
        return;
    }

    TSharedRef<FJsonObject> EventJson = MakeShared<FJsonObject>();
    EventJson->SetStringField(TEXT("type"), TEXT("SimEvent"));
    EventJson->SetStringField(TEXT("run_id"), ActiveParams.RunId);
    EventJson->SetNumberField(TEXT("sim_timestamp"), 0.0);
    EventJson->SetStringField(TEXT("event_type"), TEXT("AGV_STATE_CHANGE"));
    EventJson->SetStringField(TEXT("agv_id"), TEXT("AGV-DEMO-1"));

    TSharedPtr<FJsonObject> DataJson = MakeShared<FJsonObject>();
    DataJson->SetStringField(TEXT("from_state"), TEXT("IDLE"));
    DataJson->SetStringField(TEXT("to_state"), TEXT("MOVING_TO_PICKUP"));
    DataJson->SetNumberField(TEXT("speed"), ActiveParams.Speed);
    DataJson->SetNumberField(TEXT("battery"), 100.0);
    EventJson->SetObjectField(TEXT("data"), DataJson);

    SendSimEvent(EventJson);
    EmitProgressEvent();
}

void AAGVSimController::EmitProgressEvent()
{
    if (!bSimRunning)
    {
        return;
    }

    int32 ActiveAgvCount = 0;
    if (bRuntimeActorsInitialized)
    {
        for (AAGVActor* Agv : SpawnedAgvs)
        {
            if (IsValid(Agv) && Agv->GetStateName() != TEXT("STOPPED_COLLISION"))
            {
                ++ActiveAgvCount;
            }
        }
    }
    else
    {
        ActiveAgvCount = ActiveParams.AgvCount;
    }

    TSharedRef<FJsonObject> EventJson = MakeShared<FJsonObject>();
    EventJson->SetStringField(TEXT("type"), TEXT("SimEvent"));
    EventJson->SetStringField(TEXT("run_id"), ActiveParams.RunId);
    EventJson->SetNumberField(TEXT("sim_timestamp"), GetSimTimestampSeconds());
    EventJson->SetStringField(TEXT("event_type"), TEXT("SIM_PROGRESS"));

    TSharedPtr<FJsonObject> DataJson = MakeShared<FJsonObject>();
    DataJson->SetNumberField(TEXT("elapsed_sim_sec"), GetSimTimestampSeconds());
    DataJson->SetNumberField(TEXT("total_sim_sec"), ActiveParams.Duration);
    DataJson->SetNumberField(TEXT("tasks_completed"), GetTotalTasksCompleted());
    DataJson->SetNumberField(TEXT("active_agv_count"), ActiveAgvCount);
    EventJson->SetObjectField(TEXT("data"), DataJson);

    SendSimEvent(EventJson);
}

void AAGVSimController::CompleteDemoRun(const FString& StopReason)
{
    if (!bSimRunning)
    {
        return;
    }

    StopDemoFallback();

    TSharedRef<FJsonObject> ReportJson = MakeShared<FJsonObject>();
    ReportJson->SetStringField(TEXT("run_id"), ActiveParams.RunId);
    ReportJson->SetStringField(TEXT("stop_reason"), StopReason);
    ReportJson->SetNumberField(TEXT("sim_duration_actual"), GetSimTimestampSeconds());

    TSharedPtr<FJsonObject> KpiJson = MakeShared<FJsonObject>();
    KpiJson->SetNumberField(TEXT("throughput"), 10.0 + ActiveParams.AgvCount);
    KpiJson->SetNumberField(TEXT("avg_wait_time"), ActiveParams.BottleneckThresholdSec * 0.8);
    KpiJson->SetNumberField(TEXT("collision_risk"), 0.0);
    KpiJson->SetNumberField(TEXT("uptime"), StopReason == TEXT("STOP_COMMAND") ? 0.55 : 0.92);
    ReportJson->SetObjectField(TEXT("kpis"), KpiJson);

    TArray<TSharedPtr<FJsonValue>> TimelineArray;
    for (const TSharedPtr<FJsonObject>& Entry : TimelineEntries)
    {
        TimelineArray.Add(MakeShared<FJsonValueObject>(Entry));
    }
    ReportJson->SetArrayField(TEXT("timeline"), TimelineArray);

    SendSimComplete(ReportJson);
}

bool AAGVSimController::InitializeRuntimeSimulationActors()
{
    if (bRuntimeActorsInitialized)
    {
        return true;
    }

    UWorld* World = GetWorld();
    if (!World)
    {
        return false;
    }

    FActorSpawnParameters SpawnParams;
    SpawnParams.Owner = this;
    SpawnParams.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;

    TrafficManager = World->SpawnActor<ATrafficManagerActor>(ATrafficManagerActor::StaticClass(), GetActorLocation(), FRotator::ZeroRotator, SpawnParams);
    DispatcherActor = World->SpawnActor<ADispatcherActor>(ADispatcherActor::StaticClass(), GetActorLocation(), FRotator::ZeroRotator, SpawnParams);
    IntersectionManager = World->SpawnActor<AIntersectionManager>(AIntersectionManager::StaticClass(), GetActorLocation(), FRotator::ZeroRotator, SpawnParams);
    if (!IsValid(TrafficManager) || !IsValid(DispatcherActor) || !IsValid(IntersectionManager))
    {
        return false;
    }

    TrafficManager->ConfigureDefaultIntersection(0.42f, 0.58f, TEXT("INTERSECTION_X"));
    DispatcherActor->Configure(TrafficManager);
    IntersectionManager->Configure(0.42f, 0.58f, TEXT("INTERSECTION_X"));
    SpawnedAgvs.Reset();
    ActiveOrders.Reset();
    CompletedOrders.Reset();
    ActiveLoads.Reset();

    // AGV auto-discovery: pull every level-placed AAGVActor not already wired into AuthoredAgvs
    // (name-sorted for a stable index order) so placing AGV actors in the level is enough — no
    // manual AuthoredAgvs upkeep. The active set is then chosen by index at run time (highest
    // indices first), and paths can carry more than one AGV, so we no longer cap discovery at the
    // path count.
    {
        TArray<AAGVActor*> Discovered;
        for (TActorIterator<AAGVActor> It(World); It; ++It)
        {
            AAGVActor* Candidate = *It;
            if (IsValid(Candidate) && !AuthoredAgvs.Contains(Candidate))
            {
                Discovered.Add(Candidate);
            }
        }
        Discovered.Sort([](const AAGVActor& A, const AAGVActor& B)
        {
            return A.GetName() < B.GetName();
        });
        for (AAGVActor* Agv : Discovered)
        {
            AuthoredAgvs.Add(Agv);
        }
        if (Discovered.Num() > 0)
        {
            UE_LOG(LogTemp, Log, TEXT("AGVSimController: auto-discovered %d level AGV actor(s); AuthoredAgvs now has %d"), Discovered.Num(), AuthoredAgvs.Num());
        }
    }

    if (AuthoredAgvs.Num() < ActiveParams.AgvCount)
    {
        UE_LOG(LogTemp, Warning, TEXT("AGVSimController: %d AGVs requested but only %d AuthoredAgvs assigned in the level"), ActiveParams.AgvCount, AuthoredAgvs.Num());
        return false;
    }

    if (AuthoredPaths.Num() < 1)
    {
        UE_LOG(LogTemp, Warning, TEXT("AGVSimController: no AGV paths assigned (AuthoredPaths is empty)"));
        return false;
    }

    // Activate the highest-index AgvCount AGVs in AuthoredAgvs; the lower-index entries sit out.
    // Running with fewer AGVs than authored drops the top of the list first.
    const int32 FirstActiveIndex = AuthoredAgvs.Num() - ActiveParams.AgvCount;

    // Collect the paths that actually have a usable spline so the round-robin only maps onto routes
    // the AGVs can follow.
    TArray<AAGVPathActor*> ValidPaths;
    for (const TObjectPtr<AAGVPathActor>& PathPtr : AuthoredPaths)
    {
        AAGVPathActor* Candidate = PathPtr.Get();
        if (IsValid(Candidate) && Candidate->GetPathSpline() && Candidate->GetPathSpline()->GetSplineLength() > 0.0f)
        {
            ValidPaths.Add(Candidate);
        }
    }
    if (ValidPaths.Num() == 0)
    {
        UE_LOG(LogTemp, Warning, TEXT("AGVSimController: no AGV path has a valid spline"));
        return false;
    }

    TArray<AAGVActor*> ActiveAgvs;
    for (int32 Index = FirstActiveIndex; Index < AuthoredAgvs.Num(); ++Index)
    {
        AAGVActor* Agv = AuthoredAgvs[Index].Get();
        if (!IsValid(Agv))
        {
            UE_LOG(LogTemp, Warning, TEXT("AGVSimController: AuthoredAgvs[%d] is null"), Index);
            return false;
        }
        ActiveAgvs.Add(Agv);
    }

    // Map the AGVs to paths round-robin so they spread as evenly as possible across the routes
    // (e.g. 5 AGVs over 3 paths -> 2,2,1) instead of all piling onto whichever spline they sit
    // nearest. Count the units per path first so the AGVs that share a path can be spaced evenly
    // along its spline — that spacing is what stops same-path AGVs from converging on one entry
    // point and colliding the instant they start.
    const int32 PathCount = ValidPaths.Num();
    TArray<int32> PerPathCount;
    PerPathCount.Init(0, PathCount);
    for (int32 Slot = 0; Slot < ActiveAgvs.Num(); ++Slot)
    {
        ++PerPathCount[Slot % PathCount];
    }

    TArray<int32> PerPathAssigned;
    PerPathAssigned.Init(0, PathCount);
    for (int32 Slot = 0; Slot < ActiveAgvs.Num(); ++Slot)
    {
        const int32 PathIndex = Slot % PathCount;
        AAGVPathActor* AssignedPath = ValidPaths[PathIndex];
        const int32 SlotOnPath = PerPathAssigned[PathIndex]++;
        const int32 UnitsOnPath = FMath::Max(PerPathCount[PathIndex], 1);
        const float SplineLength = AssignedPath->GetPathSpline()->GetSplineLength();
        const float EntryDistance = SplineLength * (static_cast<float>(SlotOnPath) / static_cast<float>(UnitsOnPath));

        AAGVActor* Agv = ActiveAgvs[Slot];
        Agv->Configure(
            this,
            IntersectionManager,
            TrafficManager,
            AssignedPath,
            FString::Printf(TEXT("AGV-%d"), FirstActiveIndex + Slot + 1),
            EntryDistance,
            ActiveParams.Speed,
            ActiveParams.BottleneckThresholdSec);
        SpawnedAgvs.Add(Agv);
    }

    // The lower-index AGVs sit out this run. Reset each to a clean offline baseline so it never
    // leaks the previous run's position/battery, and surface it to the dashboard as a
    // "stopped operation" entry (red) rather than a stale active card.
    for (int32 Index = 0; Index < FirstActiveIndex; ++Index)
    {
        if (AAGVActor* OfflineAgv = AuthoredAgvs[Index].Get())
        {
            OfflineAgv->ResetToStoppedOperation(FString::Printf(TEXT("AGV-%d"), Index + 1));
        }
    }

    RebuildStationRegistry();
    UE_LOG(LogTemp, Log, TEXT("AGVSimController: Station discovery found %d station(s) after AuthoredStations/world scan"), StationRegistry ? StationRegistry->Num() : 0);

    // Autonomous Load/Unload is driven by station proximity (P6.1b); guarantee the paths carry a
    // Pickup + Dropoff pair so the loop stays green even before stations are authored in the level.
    // This also covers the previously-handled empty-registry case (replaces CreateFallbackStation).
    EnsureInteractionStations();

    // F1 ??feed live AGV positions into the congestion heatmap over a floor rect centered here.
    if (CongestionHeatmap)
    {
        CongestionHeatmap->ClearAgvs();
        const FVector Center = GetActorLocation();
        const FVector Origin(Center.X - HeatmapFloorSize.X * 0.5f, Center.Y - HeatmapFloorSize.Y * 0.5f, Center.Z);
        CongestionHeatmap->SetFloorBounds(Origin, HeatmapFloorSize);
        for (AAGVActor* Agv : SpawnedAgvs)
        {
            CongestionHeatmap->RegisterAgv(Agv);
        }
    }

    bRuntimeActorsInitialized = true;
    return true;
}

void AAGVSimController::DestroyRuntimeSimulationActors()
{
    // AGVs are level-authored (pre-placed) ??stop and reset them, do not destroy.
    for (AAGVActor* Agv : SpawnedAgvs)
    {
        if (IsValid(Agv))
        {
            Agv->StopRun();
        }
    }
    SpawnedAgvs.Reset();
    PendingStationCommands.Empty();
    for (int32 Index = AuthoredStations.Num() - 1; Index >= 0; --Index)
    {
        AStationActor* Station = AuthoredStations[Index];
        const bool bRuntimeSeeded = IsValid(Station) && Station->Tags.Contains(TEXT("RuntimeInteractionStation"));
        if (bRuntimeSeeded && Station->GetOwner() == this)
        {
            Station->Destroy();
            AuthoredStations.RemoveAt(Index);
        }
    }
    if (StationRegistry)
    {
        StationRegistry->Clear();
    }
    ActiveOrders.Reset();
    CompletedOrders.Reset();
    ActiveLoads.Reset();

    if (CongestionHeatmap)
    {
        CongestionHeatmap->ClearAgvs();
    }

    if (IsValid(IntersectionManager))
    {
        IntersectionManager->Destroy();
    }
    IntersectionManager = nullptr;

    if (IsValid(TrafficManager))
    {
        TrafficManager->Destroy();
    }
    TrafficManager = nullptr;

    if (IsValid(DispatcherActor))
    {
        DispatcherActor->Destroy();
    }
    DispatcherActor = nullptr;

    bRuntimeActorsInitialized = false;
}

bool AAGVSimController::StartRuntimeSimulation()
{
    StopDemoFallback();
    DestroyRuntimeSimulationActors();
    bCollisionHaltCompleted = false;

    if (!InitializeRuntimeSimulationActors())
    {
        return false;
    }

    KPIAccumulator->Reset();

    if (IntersectionManager)
    {
        IntersectionManager->ResetForRun();
    }
    if (TrafficManager)
    {
        TrafficManager->ResetForRun();
    }

    UWorld* World = GetWorld();
    if (!World)
    {
        return false;
    }

    // Launch the AGVs one at a time, AgvStartStaggerSeconds apart, so they don't all accelerate
    // into the same junction on frame one. The first starts now; each later one is started by a
    // one-shot timer. An AGV only becomes dispatchable once StartRun sets bRunActive, so this
    // also staggers when each unit first picks up work and begins moving.
    for (FTimerHandle& Handle : StaggeredStartTimerHandles)
    {
        World->GetTimerManager().ClearTimer(Handle);
    }
    StaggeredStartTimerHandles.Reset();

    TWeakObjectPtr<AAGVSimController> WeakThis(this);
    for (int32 Index = 0; Index < SpawnedAgvs.Num(); ++Index)
    {
        AAGVActor* Agv = SpawnedAgvs[Index];
        if (!IsValid(Agv))
        {
            continue;
        }

        if (Index == 0 || AgvStartStaggerSeconds <= 0.0f)
        {
            Agv->StartRun();
            continue;
        }

        TWeakObjectPtr<AAGVActor> WeakAgv(Agv);
        FTimerHandle Handle;
        World->GetTimerManager().SetTimer(
            Handle,
            FTimerDelegate::CreateLambda([WeakThis, WeakAgv]()
            {
                AAGVSimController* Self = WeakThis.Get();
                AAGVActor* DelayedAgv = WeakAgv.Get();
                if (Self && DelayedAgv && Self->bSimRunning && !Self->bSimPaused)
                {
                    DelayedAgv->StartRun();
                }
            }),
            Index * AgvStartStaggerSeconds,
            false);
        StaggeredStartTimerHandles.Add(Handle);
    }

    World->GetTimerManager().SetTimer(DemoProgressTimerHandle, this, &AAGVSimController::EmitProgressEvent, 1.0f, true, 1.0f);
    World->GetTimerManager().SetTimer(TelemetryTimerHandle, this, &AAGVSimController::EmitTelemetry, 0.2f, true, 0.2f);

    // Keep the cell alive: assign deliveries to idle AGVs immediately and re-check on a timer
    // so a freshly Idle AGV picks up new work. Chat /agv/command still overrides specific AGVs.
    DispatchIdleAgvs();
    World->GetTimerManager().SetTimer(AutoDispatchTimerHandle, this, &AAGVSimController::DispatchIdleAgvs, 1.5f, true, 1.5f);

    RescheduleSimulationCompleteTimer();

    return true;
}

void AAGVSimController::DispatchIdleAgvs()
{
    if (!bSimRunning || bSimPaused)
    {
        return;
    }

    // The dispatcher is the sole assignment authority (P6.1c): autonomous dispatch is gated on an
    // eligible Pickup station rather than blindly assigning every idle AGV. Station metadata
    // (capacity/capability/zone) feeds that eligibility via ScoreAgvForStation.
    TArray<AStationActor*> PickupStations;
    if (StationRegistry)
    {
        for (const TPair<int32, TObjectPtr<AStationActor>>& Pair : StationRegistry->GetStations())
        {
            if (AStationActor* Station = Pair.Value.Get())
            {
                if (Station->StationKind == EStationKind::Pickup)
                {
                    PickupStations.Add(Station);
                }
            }
        }
    }

    for (AAGVActor* Agv : SpawnedAgvs)
    {
        if (!IsValid(Agv) || !Agv->IsAvailableForDispatch())
        {
            continue;
        }

        if (!DispatcherActor)
        {
            Agv->AssignDeliveryTask(nullptr);
            continue;
        }

        FDispatchScoreBreakdown Score;
        if (DispatcherActor->SelectStationForAgv(Agv, PickupStations, Score))
        {
            Agv->AssignDeliveryTask(nullptr);
        }
        // No eligible pickup ??leave the AGV idle this cycle (re-evaluated on the next dispatch tick).
    }
}

void AAGVSimController::CheckAgvProximityCollisions()
{
    const float ThreshSq = CollisionDetectionRadius * CollisionDetectionRadius;
    for (int32 I = 0; I < SpawnedAgvs.Num(); ++I)
    {
        AAGVActor* AgvA = SpawnedAgvs[I];
        if (!IsValid(AgvA) || AgvA->GetStateName() == TEXT("STOPPED_COLLISION"))
        {
            continue;
        }

        for (int32 J = I + 1; J < SpawnedAgvs.Num(); ++J)
        {
            AAGVActor* AgvB = SpawnedAgvs[J];
            if (!IsValid(AgvB) || AgvB->GetStateName() == TEXT("STOPPED_COLLISION"))
            {
                continue;
            }

            const float DistSq = static_cast<float>(FVector::DistSquared(AgvA->GetActorLocation(), AgvB->GetActorLocation()));
            if (DistSq < ThreshSq)
            {
                AgvA->ForceCollisionStop(AgvB);
                AgvB->ForceCollisionStop(AgvA);
            }
        }
    }

    // If the collisions above (or earlier) have stopped every AGV in the cell, the run can no
    // longer make progress. Terminate it once and report the halt to the backend; the existing
    // completion path tags stop_reason="collision_halt" so the chatbot reports the collision.
    if (!bCollisionHaltCompleted && AllSpawnedAgvsCollisionStopped())
    {
        bCollisionHaltCompleted = true;
        CompleteRuntimeRun(TEXT("collision_halt"));
    }
}

bool AAGVSimController::AllSpawnedAgvsCollisionStopped() const
{
    if (!bSimRunning)
    {
        return false;
    }
    int32 ValidCount = 0;
    for (const AAGVActor* Agv : SpawnedAgvs)
    {
        if (!IsValid(Agv))
        {
            continue;
        }
        ++ValidCount;
        if (Agv->GetStateName() != TEXT("STOPPED_COLLISION"))
        {
            return false;
        }
    }
    return ValidCount > 0;
}

void AAGVSimController::RegisterDebugConsoleCommands()
{
    if (DebugConsoleCommands.Num() > 0)
    {
        return;
    }

    IConsoleManager& Console = IConsoleManager::Get();
    TWeakObjectPtr<AAGVSimController> WeakThis(this);

    DebugConsoleCommands.Add(Console.RegisterConsoleCommand(
        TEXT("Vcore.Start"),
        TEXT("Start the AGV cell in PIE. Args: [Speed=4.0] [AgvCount=3]"),
        FConsoleCommandWithArgsDelegate::CreateLambda([WeakThis](const TArray<FString>& Args)
        {
            if (AAGVSimController* C = WeakThis.Get())
            {
                const float Speed = Args.Num() > 0 ? FCString::Atof(*Args[0]) : 4.0f;
                const int32 Count = Args.Num() > 1 ? FCString::Atoi(*Args[1]) : 3;
                C->VcoreStart(Speed, Count);
            }
        }),
        ECVF_Default));

    DebugConsoleCommands.Add(Console.RegisterConsoleCommand(
        TEXT("Vcore.Stop"),
        TEXT("Stop the AGV cell."),
        FConsoleCommandWithArgsDelegate::CreateLambda([WeakThis](const TArray<FString>&)
        {
            if (AAGVSimController* C = WeakThis.Get())
            {
                C->VcoreStop();
            }
        }),
        ECVF_Default));

    DebugConsoleCommands.Add(Console.RegisterConsoleCommand(
        TEXT("Vcore.Assign"),
        TEXT("Assign a delivery task to an AGV. Args: [AgvIndex=0]"),
        FConsoleCommandWithArgsDelegate::CreateLambda([WeakThis](const TArray<FString>& Args)
        {
            if (AAGVSimController* C = WeakThis.Get())
            {
                C->VcoreAssign(Args.Num() > 0 ? FCString::Atoi(*Args[0]) : 0);
            }
        }),
        ECVF_Default));

    DebugConsoleCommands.Add(Console.RegisterConsoleCommand(
        TEXT("Vcore.Station"),
        TEXT("Direct an AGV to a station dock. Args: [AgvIndex=0] [StationId=1]"),
        FConsoleCommandWithArgsDelegate::CreateLambda([WeakThis](const TArray<FString>& Args)
        {
            if (AAGVSimController* C = WeakThis.Get())
            {
                const int32 AgvIndex = Args.Num() > 0 ? FCString::Atoi(*Args[0]) : 0;
                const int32 StationId = Args.Num() > 1 ? FCString::Atoi(*Args[1]) : 1;
                C->VcoreStation(AgvIndex, StationId);
            }
        }),
        ECVF_Default));
}

void AAGVSimController::UnregisterDebugConsoleCommands()
{
    IConsoleManager& Console = IConsoleManager::Get();
    for (IConsoleCommand* Command : DebugConsoleCommands)
    {
        if (Command)
        {
            Console.UnregisterConsoleObject(Command);
        }
    }
    DebugConsoleCommands.Reset();
}

void AAGVSimController::VcoreStart(float Speed, int32 AgvCount)
{
    if (bSimRunning)
    {
        UE_LOG(LogTemp, Warning, TEXT("VcoreStart: a simulation is already running; call VcoreStop first"));
        return;
    }

    ActiveParams = FSimStartParams();
    ActiveParams.RunId = TEXT("PIE_TEST");
    ActiveParams.Speed = FMath::Max(Speed, 0.1f);
    ActiveParams.AgvCount = FMath::Max(AgvCount, 1);

    bSimPaused = false;
    SpeedMultiplier = ActiveParams.Speed;
    ApplySimSpeed(SpeedMultiplier);
    bSimRunning = true;
    DemoRunStartedAtSeconds = FPlatformTime::Seconds();
    SimElapsedSeconds = 0.0;
    LastSimClockRealSeconds = DemoRunStartedAtSeconds;
    SimTargetDurationSeconds = 0.0;

    if (!StartRuntimeSimulation())
    {
        bSimRunning = false;
        UE_LOG(LogTemp, Warning, TEXT("VcoreStart: StartRuntimeSimulation failed (check AuthoredPaths and the StateTree assignment)"));
        return;
    }

    UE_LOG(LogTemp, Display, TEXT("VcoreStart: %d AGV(s) running at x%.1f. Use VcoreAssign <i> / VcoreStation <i> <id>."), ActiveParams.AgvCount, ActiveParams.Speed);
}

void AAGVSimController::VcoreStop()
{
    StopRuntimeSimulation();
    bSimRunning = false;
    bSimPaused = false;
    UE_LOG(LogTemp, Display, TEXT("VcoreStop: simulation stopped"));
}

void AAGVSimController::VcoreAssign(int32 AgvIndex)
{
    if (!SpawnedAgvs.IsValidIndex(AgvIndex) || !IsValid(SpawnedAgvs[AgvIndex]))
    {
        UE_LOG(LogTemp, Warning, TEXT("VcoreAssign: no AGV at index %d (run VcoreStart first)"), AgvIndex);
        return;
    }

    const bool bAssigned = SpawnedAgvs[AgvIndex]->AssignDeliveryTask(nullptr);
    UE_LOG(LogTemp, Display, TEXT("VcoreAssign: AGV %d delivery task %s"), AgvIndex, bAssigned ? TEXT("started") : TEXT("REJECTED (StateTree not running?)"));
}

void AAGVSimController::VcoreStation(int32 AgvIndex, int32 StationId)
{
    if (!SpawnedAgvs.IsValidIndex(AgvIndex) || !IsValid(SpawnedAgvs[AgvIndex]))
    {
        UE_LOG(LogTemp, Warning, TEXT("VcoreStation: no AGV at index %d (run VcoreStart first)"), AgvIndex);
        return;
    }

    AStationActor* Station = ResolveStation(StationId);
    if (!IsValid(Station))
    {
        UE_LOG(LogTemp, Warning, TEXT("VcoreStation: no station with id %d"), StationId);
        return;
    }

    const bool bDirected = SpawnedAgvs[AgvIndex]->DirectToStation(Station, nullptr);
    UE_LOG(LogTemp, Display, TEXT("VcoreStation: AGV %d -> station %d %s"), AgvIndex, StationId, bDirected ? TEXT("directed") : TEXT("REJECTED"));
}

void AAGVSimController::StopRuntimeSimulation()
{
    UWorld* World = GetWorld();
    if (World)
    {
        World->GetTimerManager().ClearTimer(SimulationCompleteTimerHandle);
        World->GetTimerManager().ClearTimer(DemoProgressTimerHandle);
        World->GetTimerManager().ClearTimer(TelemetryTimerHandle);
        World->GetTimerManager().ClearTimer(AutoDispatchTimerHandle);
        for (FTimerHandle& Handle : StaggeredStartTimerHandles)
        {
            World->GetTimerManager().ClearTimer(Handle);
        }
        StaggeredStartTimerHandles.Reset();
    }

    for (AAGVActor* Agv : SpawnedAgvs)
    {
        if (IsValid(Agv))
        {
            Agv->StopRun();
        }
    }
}

void AAGVSimController::CompleteRuntimeRun(const FString& StopReason)
{
    if (!bSimRunning)
    {
        return;
    }

    StopRuntimeSimulation();
    SendSimComplete(BuildRuntimeReport(StopReason));
}

TSharedRef<FJsonObject> AAGVSimController::BuildRuntimeReport(const FString& StopReason) const
{
    TSharedRef<FJsonObject> ReportJson = MakeShared<FJsonObject>();
    ReportJson->SetStringField(TEXT("run_id"), ActiveParams.RunId);
    ReportJson->SetStringField(TEXT("stop_reason"), StopReason);

    const double SimDurationActual = GetSimTimestampSeconds();
    ReportJson->SetNumberField(TEXT("sim_duration_actual"), SimDurationActual);

    TSharedPtr<FJsonObject> KpiJson = KPIAccumulator->BuildRuntimeKpis(
        SimDurationActual,
        SpawnedAgvs,
        IntersectionManager,
        TrafficManager);
    KpiJson->SetNumberField(TEXT("avg_route_wait_time"), TrafficManager ? TrafficManager->GetAverageWaitTimeSeconds() : 0.0);
    KpiJson->SetNumberField(TEXT("blocked_segments"), TrafficManager ? TrafficManager->GetBlockedSegmentCount() : 0);
    ReportJson->SetObjectField(TEXT("kpis"), KpiJson);

    // F4 ??evaluate agent acceptance criteria against the final KPIs and attach the verdict.
    if (ScenarioVerifier && ScenarioVerifier->HasChecks())
    {
        const FProcessKpiSnapshot Snapshot = KPIAccumulator->BuildScenarioSnapshot(
            SimDurationActual,
            GetActiveAgvCount(),
            SpawnedAgvs,
            IntersectionManager,
            TrafficManager);

        const FScenarioVerdict Verdict = ScenarioVerifier->Evaluate(Snapshot);

        TSharedPtr<FJsonObject> VerdictJson = MakeShared<FJsonObject>();
        VerdictJson->SetBoolField(TEXT("passed"), Verdict.bPassed);
        VerdictJson->SetNumberField(TEXT("checks_total"), Verdict.PassedLabels.Num() + Verdict.FailedLabels.Num());

        TArray<TSharedPtr<FJsonValue>> PassedArray;
        for (const FString& Label : Verdict.PassedLabels)
        {
            PassedArray.Add(MakeShared<FJsonValueString>(Label));
        }
        VerdictJson->SetArrayField(TEXT("passed_labels"), PassedArray);

        TArray<TSharedPtr<FJsonValue>> FailedArray;
        for (const FString& Label : Verdict.FailedLabels)
        {
            FailedArray.Add(MakeShared<FJsonValueString>(Label));
        }
        VerdictJson->SetArrayField(TEXT("failed_labels"), FailedArray);

        ReportJson->SetObjectField(TEXT("verdict"), VerdictJson);
    }

    // Append the final congestion heatmap grid so the web report card can render it.
    if (CongestionHeatmap && CongestionHeatmap->GetDensityArray().Num() > 0)
    {
        TArray<TSharedPtr<FJsonValue>> GridValues;
        for (const float Cell : CongestionHeatmap->GetDensityArray())
        {
            GridValues.Add(MakeShared<FJsonValueNumber>(FMath::RoundToFloat(Cell * 100.f) / 100.f));
        }
        KpiJson->SetArrayField(TEXT("heatmap_grid"), GridValues);

        TArray<TSharedPtr<FJsonValue>> TraversedValues;
        for (const uint8 bVisited : CongestionHeatmap->GetVisitedCells())
        {
            TraversedValues.Add(MakeShared<FJsonValueBoolean>(bVisited != 0));
        }
        KpiJson->SetArrayField(TEXT("heatmap_traversed_grid"), TraversedValues);
        KpiJson->SetNumberField(TEXT("heatmap_res_x"), CongestionHeatmap->GetGridResX());
        KpiJson->SetNumberField(TEXT("heatmap_res_y"), CongestionHeatmap->GetGridResY());
    }

    TArray<TSharedPtr<FJsonValue>> TimelineArray;
    for (const TSharedPtr<FJsonObject>& Entry : TimelineEntries)
    {
        TimelineArray.Add(MakeShared<FJsonValueObject>(Entry));
    }
    ReportJson->SetArrayField(TEXT("timeline"), TimelineArray);

    return ReportJson;
}


void AAGVSimController::ResetActiveRun()
{
    StopDemoFallback();
    StopRuntimeSimulation();
    DestroyRuntimeSimulationActors();
    bSimRunning = false;
    bSimPaused = false;
    SpeedMultiplier = 1.0f;
    ActiveSessionId.Reset();
    ActiveCorrelationId.Reset();
    ActiveCommandId.Reset();
    DemoRunStartedAtSeconds = 0.0;
    SimElapsedSeconds = 0.0;
    LastSimClockRealSeconds = 0.0;
    SimTargetDurationSeconds = 0.0;
    WebSocketConnectAttempts = 0;
    ActiveParams = FSimStartParams{};
    if (ScenarioVerifier)
    {
        ScenarioVerifier->ClearChecks();
    }
    DisconnectWebSocket();
}

void AAGVSimController::ResetActiveRunForTeardown()
{
    StopDemoFallback();
    StopRuntimeSimulation();
    DestroyRuntimeSimulationActors();
    bSimRunning = false;
    bSimPaused = false;
    SpeedMultiplier = 1.0f;
    ActiveSessionId.Reset();
    ActiveCorrelationId.Reset();
    ActiveCommandId.Reset();
    DemoRunStartedAtSeconds = 0.0;
    SimElapsedSeconds = 0.0;
    LastSimClockRealSeconds = 0.0;
    SimTargetDurationSeconds = 0.0;
    WebSocketConnectAttempts = 0;
    KPIAccumulator->Reset();
    TimelineEntries.Reset();
    ActiveParams = FSimStartParams{};
    if (ScenarioVerifier)
    {
        ScenarioVerifier->ClearChecks();
    }
    DisconnectWebSocket();
}

void AAGVSimController::RecordTimelineEvent(const TSharedRef<FJsonObject>& EventJson)
{
    if (!EventJson->HasField(TEXT("sim_timestamp")) || !EventJson->HasField(TEXT("event_type")))
    {
        return;
    }

    TSharedPtr<FJsonObject> TimelineEntry = MakeShared<FJsonObject>();
    TimelineEntry->SetNumberField(TEXT("sim_timestamp"), EventJson->GetNumberField(TEXT("sim_timestamp")));
    TimelineEntry->SetStringField(TEXT("event_type"), EventJson->GetStringField(TEXT("event_type")));

    if (EventJson->HasTypedField<EJson::String>(TEXT("agv_id")))
    {
        TimelineEntry->SetStringField(TEXT("agv_id"), EventJson->GetStringField(TEXT("agv_id")));
    }

    if (EventJson->HasTypedField<EJson::Object>(TEXT("data")))
    {
        TimelineEntry->SetObjectField(TEXT("data"), EventJson->GetObjectField(TEXT("data")));
    }
    else
    {
        TimelineEntry->SetObjectField(TEXT("data"), MakeShared<FJsonObject>());
    }

    TimelineEntries.Add(TimelineEntry);
}

TSharedPtr<FJsonObject> AAGVSimController::ParseRequestBody(const FHttpServerRequest& Request)
{
    if (Request.Body.Num() == 0)
    {
        return MakeShared<FJsonObject>();
    }
    // Request.Body is a TArray<uint8> with NO null terminator. Converting it as a
    // C-string (UTF8_TO_TCHAR over GetData()) overreads adjacent heap until a stray
    // null byte, intermittently corrupting the JSON ("Invalid JSON" on random calls).
    // Convert exactly Request.Body.Num() bytes instead.
    FString Body;
    const auto Converted = StringCast<TCHAR>(
        reinterpret_cast<const UTF8CHAR*>(Request.Body.GetData()), Request.Body.Num());
    Body.AppendChars(Converted.Get(), Converted.Length());
    TSharedPtr<FJsonObject> Json;
    TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Body);
    if (!FJsonSerializer::Deserialize(Reader, Json) || !Json.IsValid())
    {
        return nullptr;
    }
    return Json;
}

void AAGVSimController::RespondJson(const FHttpResultCallback& OnComplete, const FString& Body)
{
    FTCHARToUTF8 Converted(*Body);
    TArray<uint8> ResponseBytes;
    ResponseBytes.Append(reinterpret_cast<const uint8*>(Converted.Get()), Converted.Length());
    auto Response = FHttpServerResponse::Create(ResponseBytes, TEXT("application/json"));
    OnComplete(MoveTemp(Response));
}

void AAGVSimController::ApplySimSpeed(float Multiplier)
{
    if (UWorld* World = GetWorld())
    {
        UGameplayStatics::SetGlobalTimeDilation(World, FMath::Clamp(Multiplier, 0.0f, 20.0f));
    }
}

int32 AAGVSimController::GetActiveAgvCount() const
{
    if (!bRuntimeActorsInitialized)
    {
        return bSimRunning ? ActiveParams.AgvCount : 0;
    }
    int32 Count = 0;
    for (const AAGVActor* Agv : SpawnedAgvs)
    {
        if (IsValid(Agv) && Agv->GetStateName() != TEXT("STOPPED_COLLISION"))
        {
            ++Count;
        }
    }
    return Count;
}

TSharedRef<FJsonObject> AAGVSimController::BuildStatusJson() const
{
    TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
    Json->SetStringField(TEXT("cell_id"), CellId);
    Json->SetStringField(TEXT("run_id"), ActiveParams.RunId);
    Json->SetBoolField(TEXT("running"), bSimRunning);
    Json->SetBoolField(TEXT("paused"), bSimPaused);
    Json->SetNumberField(TEXT("speed_multiplier"), SpeedMultiplier);
    KPIAccumulator->WriteStatusFields(
        *Json,
        GetSimTimestampSeconds(),
        bSimRunning,
        bSimPaused,
        IntersectionManager,
        TrafficManager);
    Json->SetNumberField(TEXT("active_agvs"), GetActiveAgvCount());
    // Maximum AGVs the cell can run = the level's placed AGV actors, provided at least one path
    // exists to put them on. Paths can carry multiple AGVs (active units round-robin across paths,
    // spaced out along each spline), so the count is no longer capped by the number of paths.
    // Scanned from the level so the count reflects placed AGV actors even before a run auto-fills
    // AuthoredAgvs. The backend reads this so the optimizer's search upper bound tracks the real
    // cell instead of a hardcoded constant.
    int32 LevelAgvCount = AuthoredAgvs.Num();
    if (const UWorld* StatusWorld = GetWorld())
    {
        int32 ScannedAgvs = 0;
        for (TActorIterator<AAGVActor> It(StatusWorld); It; ++It)
        {
            if (IsValid(*It))
            {
                ++ScannedAgvs;
            }
        }
        LevelAgvCount = FMath::Max(LevelAgvCount, ScannedAgvs);
    }
    const int32 MaxAgvs = AuthoredPaths.Num() > 0 ? LevelAgvCount : 0;
    Json->SetNumberField(TEXT("max_agvs"), MaxAgvs);
    Json->SetNumberField(TEXT("active_orders"), ActiveOrders.Num());
    int32 QueuedOrders = 0;
    for (const UTransportOrder* Order : ActiveOrders)
    {
        if (Order && Order->State == ETransportOrderState::Queued)
        {
            ++QueuedOrders;
        }
    }
    Json->SetNumberField(TEXT("queued_orders"), QueuedOrders);
    Json->SetNumberField(TEXT("completed_orders"), CompletedOrders.Num());
    Json->SetNumberField(TEXT("station_count"), StationRegistry ? StationRegistry->Num() : 0);
    Json->SetNumberField(TEXT("blocked_segments"), TrafficManager ? TrafficManager->GetBlockedSegmentCount() : 0);
    Json->SetNumberField(TEXT("avg_route_wait_time"), TrafficManager ? TrafficManager->GetAverageWaitTimeSeconds() : 0.0);
    Json->SetBoolField(TEXT("dispatcher_ready"), DispatcherActor != nullptr);
    Json->SetBoolField(TEXT("traffic_manager_ready"), TrafficManager != nullptr);

    TArray<TSharedPtr<FJsonValue>> StationsJson;
    if (StationRegistry)
    {
        for (const TPair<int32, TObjectPtr<AStationActor>>& Pair : StationRegistry->GetStations())
        {
            const AStationActor* Station = Pair.Value.Get();
            if (!IsValid(Station))
            {
                continue;
            }

            TSharedPtr<FJsonObject> StationJson = MakeShared<FJsonObject>();
            StationJson->SetNumberField(TEXT("station_id"), Pair.Key);
            StationJson->SetNumberField(TEXT("kind"), static_cast<int32>(Station->StationKind));
            StationJson->SetStringField(TEXT("zone_id"), Station->ZoneId);
            StationJson->SetBoolField(TEXT("ready"), Station->bReady);
            StationJson->SetBoolField(TEXT("accessible"), Station->bAccessible);
            StationJson->SetStringField(TEXT("reserved_by_agv_id"), Station->GetReservedByAgvId());
            StationsJson.Add(MakeShared<FJsonValueObject>(StationJson));
        }
    }
    Json->SetArrayField(TEXT("stations"), StationsJson);
    Json->SetNumberField(TEXT("progress_percent"), ComputeProgressPercent());
    Json->SetStringField(TEXT("progress_basis"), TEXT("simulated_time"));
    Json->SetNumberField(TEXT("sim_elapsed_seconds"), SimElapsedSeconds);
    Json->SetNumberField(TEXT("sim_target_duration_seconds"), SimTargetDurationSeconds > 0.0 ? SimTargetDurationSeconds : static_cast<double>(ActiveParams.Duration));
    return Json;
}

float AAGVSimController::ComputeProgressPercent() const
{
    if (!bSimRunning)
    {
        return 0.0f;
    }
    const double Elapsed = UpdateSimClock();
    const double Target = FMath::Max(SimTargetDurationSeconds > 0.0 ? SimTargetDurationSeconds : static_cast<double>(ActiveParams.Duration), 1.0);
    return static_cast<float>(FMath::Clamp(Elapsed / Target, 0.0, 1.0) * 100.0);
}

void AAGVSimController::SendChatEvent(
    const FString& SessionId,
    const FString& CorrelationId,
    const FString& CommandId,
    const FString& EventType,
    const TSharedPtr<FJsonObject>& Payload)
{
    if (SessionId.IsEmpty())
    {
        return;
    }

    TSharedRef<FJsonObject> EventJson = MakeShared<FJsonObject>();
    EventJson->SetStringField(TEXT("session_id"), SessionId);
    EventJson->SetStringField(TEXT("correlation_id"), CorrelationId);
    if (!CommandId.IsEmpty())
    {
        EventJson->SetStringField(TEXT("command_id"), CommandId);
    }
    EventJson->SetStringField(TEXT("event_type"), EventType);
    EventJson->SetObjectField(TEXT("payload"), Payload.IsValid() ? Payload.ToSharedRef() : MakeShared<FJsonObject>());

    FString Body;
    TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Body);
    FJsonSerializer::Serialize(EventJson, Writer);

    const FString Url = FString::Printf(TEXT("http://%s:%d/internal/ue5/events"), *BackendHost, BackendPort);
    TSharedRef<IHttpRequest, ESPMode::ThreadSafe> HttpReq = FHttpModule::Get().CreateRequest();
    HttpReq->SetURL(Url);
    HttpReq->SetVerb(TEXT("POST"));
    HttpReq->SetHeader(TEXT("Content-Type"), TEXT("application/json"));
    HttpReq->SetHeader(TEXT("X-AGV-API-Key"), APIKey);
    HttpReq->SetContentAsString(Body);
    HttpReq->ProcessRequest();
}

bool AAGVSimController::HandleSimPauseRequest(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete)
{
    TSharedPtr<FJsonObject> Json = ParseRequestBody(Request);
    if (!Json.IsValid())
    {
        OnComplete(FHttpServerResponse::Error(EHttpServerResponseCodes::BadRequest, TEXT(""), TEXT("Invalid JSON")));
        return true;
    }
    const FString SessionId = Json->HasField(TEXT("session_id")) ? Json->GetStringField(TEXT("session_id")) : FString();
    const FString CorrelationId = Json->HasField(TEXT("correlation_id")) ? Json->GetStringField(TEXT("correlation_id")) : FString();
    const FString CommandId = Json->HasField(TEXT("command_id")) ? Json->GetStringField(TEXT("command_id")) : FString();

    AAGVSimController* Controller = this;
    AsyncTask(ENamedThreads::GameThread, [Controller, SessionId, CorrelationId, CommandId]()
    {
        if (!IsValid(Controller) || !Controller->bSimRunning)
        {
            return;
        }
        Controller->UpdateSimClock();
        Controller->bSimPaused = true;
        if (UWorld* World = Controller->GetWorld())
        {
            World->GetTimerManager().ClearTimer(Controller->SimulationCompleteTimerHandle);
        }
        Controller->ApplySimSpeed(0.0f);
        TSharedPtr<FJsonObject> Payload = MakeShared<FJsonObject>();
        Payload->SetStringField(TEXT("action"), TEXT("paused"));
        Controller->SendChatEvent(SessionId, CorrelationId, CommandId, TEXT("robot.command.completed"), Payload);
    });

    RespondJson(OnComplete, TEXT("{\"status\":\"accepted\",\"action\":\"pause\"}"));
    return true;
}

bool AAGVSimController::HandleSimResumeRequest(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete)
{
    TSharedPtr<FJsonObject> Json = ParseRequestBody(Request);
    if (!Json.IsValid())
    {
        OnComplete(FHttpServerResponse::Error(EHttpServerResponseCodes::BadRequest, TEXT(""), TEXT("Invalid JSON")));
        return true;
    }
    const FString SessionId = Json->HasField(TEXT("session_id")) ? Json->GetStringField(TEXT("session_id")) : FString();
    const FString CorrelationId = Json->HasField(TEXT("correlation_id")) ? Json->GetStringField(TEXT("correlation_id")) : FString();
    const FString CommandId = Json->HasField(TEXT("command_id")) ? Json->GetStringField(TEXT("command_id")) : FString();

    AAGVSimController* Controller = this;
    AsyncTask(ENamedThreads::GameThread, [Controller, SessionId, CorrelationId, CommandId]()
    {
        if (!IsValid(Controller) || !Controller->bSimRunning)
        {
            return;
        }
        Controller->LastSimClockRealSeconds = FPlatformTime::Seconds();
        Controller->bSimPaused = false;
        Controller->ApplySimSpeed(Controller->SpeedMultiplier);
        Controller->RescheduleSimulationCompleteTimer();
        TSharedPtr<FJsonObject> Payload = MakeShared<FJsonObject>();
        Payload->SetStringField(TEXT("action"), TEXT("resumed"));
        Controller->SendChatEvent(SessionId, CorrelationId, CommandId, TEXT("robot.command.completed"), Payload);
    });

    RespondJson(OnComplete, TEXT("{\"status\":\"accepted\",\"action\":\"resume\"}"));
    return true;
}

bool AAGVSimController::HandleSimSpeedRequest(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete)
{
    TSharedPtr<FJsonObject> Json = ParseRequestBody(Request);
    if (!Json.IsValid())
    {
        OnComplete(FHttpServerResponse::Error(EHttpServerResponseCodes::BadRequest, TEXT(""), TEXT("Invalid JSON")));
        return true;
    }
    const TSharedPtr<FJsonObject>* ParamsObjPtr = nullptr;
    Json->TryGetObjectField(TEXT("parameters"), ParamsObjPtr);
    const TSharedPtr<FJsonObject> ParamsObj = (ParamsObjPtr && ParamsObjPtr->IsValid()) ? *ParamsObjPtr : Json;
    double NumberValue = 1.0;
    ParamsObj->TryGetNumberField(TEXT("speed_multiplier"), NumberValue);
    const float Multiplier = FMath::Max(static_cast<float>(NumberValue), 0.1f);

    const FString SessionId = Json->HasField(TEXT("session_id")) ? Json->GetStringField(TEXT("session_id")) : FString();
    const FString CorrelationId = Json->HasField(TEXT("correlation_id")) ? Json->GetStringField(TEXT("correlation_id")) : FString();
    const FString CommandId = Json->HasField(TEXT("command_id")) ? Json->GetStringField(TEXT("command_id")) : FString();

    AAGVSimController* Controller = this;
    AsyncTask(ENamedThreads::GameThread, [Controller, SessionId, CorrelationId, CommandId, Multiplier]()
    {
        if (!IsValid(Controller))
        {
            return;
        }
        Controller->UpdateSimClock();
        Controller->SpeedMultiplier = Multiplier;
        Controller->ActiveParams.Speed = Multiplier;
        if (!Controller->bSimPaused)
        {
            Controller->ApplySimSpeed(Multiplier);
            Controller->LastSimClockRealSeconds = FPlatformTime::Seconds();
            Controller->RescheduleSimulationCompleteTimer();
        }
        TSharedPtr<FJsonObject> Payload = MakeShared<FJsonObject>();
        Payload->SetNumberField(TEXT("speed_multiplier"), Multiplier);
        Controller->SendChatEvent(SessionId, CorrelationId, CommandId, TEXT("robot.command.completed"), Payload);
    });

    RespondJson(OnComplete, FString::Printf(TEXT("{\"status\":\"accepted\",\"speed_multiplier\":%.2f}"), Multiplier));
    return true;
}

bool AAGVSimController::HandleAgvCommandRequest(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete)
{
    TSharedPtr<FJsonObject> Json = ParseRequestBody(Request);
    if (!Json.IsValid())
    {
        OnComplete(FHttpServerResponse::Error(EHttpServerResponseCodes::BadRequest, TEXT(""), TEXT("Invalid JSON")));
        return true;
    }
    const TSharedPtr<FJsonObject>* ParamsObjPtr = nullptr;
    Json->TryGetObjectField(TEXT("parameters"), ParamsObjPtr);
    const TSharedPtr<FJsonObject> ParamsObj = (ParamsObjPtr && ParamsObjPtr->IsValid()) ? *ParamsObjPtr : Json;
    double StationNumber = 0.0;
    ParamsObj->TryGetNumberField(TEXT("station_id"), StationNumber);
    const int32 StationId = static_cast<int32>(StationNumber);
    FString RequestedAgvId;
    ParamsObj->TryGetStringField(TEXT("agv_id"), RequestedAgvId);
    FString LoadType;
    ParamsObj->TryGetStringField(TEXT("load_type"), LoadType);
    double PriorityNumber = 0.0;
    ParamsObj->TryGetNumberField(TEXT("priority"), PriorityNumber);
    const int32 Priority = static_cast<int32>(PriorityNumber);

    const FString CommandName = Json->HasField(TEXT("command_name")) ? Json->GetStringField(TEXT("command_name")) : FString();
    const FString SessionId = Json->HasField(TEXT("session_id")) ? Json->GetStringField(TEXT("session_id")) : FString();
    const FString CorrelationId = Json->HasField(TEXT("correlation_id")) ? Json->GetStringField(TEXT("correlation_id")) : FString();
    const FString CommandId = Json->HasField(TEXT("command_id")) ? Json->GetStringField(TEXT("command_id")) : FString();

    AAGVSimController* Controller = this;
    AsyncTask(ENamedThreads::GameThread, [Controller, SessionId, CorrelationId, CommandId, CommandName, StationId, RequestedAgvId, LoadType, Priority]()
    {
        if (!IsValid(Controller))
        {
            return;
        }

        const bool bIsDriveCommand = CommandName == TEXT("move_to_station")
            || CommandName == TEXT("run_station_task")
            || CommandName == TEXT("inspect_station");
        AStationActor* TargetStation = bIsDriveCommand ? Controller->ResolveStation(StationId) : nullptr;
        FDispatchScoreBreakdown DispatchScore;
        AAGVActor* TargetAgv = bIsDriveCommand ? Controller->ResolveCommandAgv(RequestedAgvId, TargetStation, &DispatchScore) : nullptr;

        if (TargetAgv && TargetStation && TargetStation->ReserveForAgv(TargetAgv->GetAgvId()))
        {
            UTransportOrder* Order = Controller->CreateStationCommandOrder(StationId, LoadType, Priority);

            // Retarget the AGV; completion is deferred until it reaches the anchor.
            if (!TargetAgv->DirectToStation(TargetStation, Order))
            {
                TargetStation->ReleaseReservation(TargetAgv->GetAgvId());
                if (Order)
                {
                    Order->MarkFailed(TEXT("state_tree_control_rejected"));
                }

                TSharedPtr<FJsonObject> Payload = MakeShared<FJsonObject>();
                Payload->SetNumberField(TEXT("station_id"), StationId);
                Payload->SetStringField(TEXT("agv_id"), TargetAgv->GetAgvId());
                Payload->SetStringField(TEXT("command_name"), CommandName);
                Payload->SetStringField(TEXT("reason"), TEXT("state_tree_control_rejected"));
                Controller->SendChatEvent(SessionId, CorrelationId, CommandId, TEXT("robot.command.completed"), Payload);
                return;
            }

            Controller->PendingStationCommands.Add(TargetAgv->GetAgvId(),
                FPendingStationCommand{ SessionId, CorrelationId, CommandId, CommandName, StationId });

            TSharedPtr<FJsonObject> MovingPayload = MakeShared<FJsonObject>();
            MovingPayload->SetNumberField(TEXT("target_station_id"), StationId);
            MovingPayload->SetStringField(TEXT("agv_id"), TargetAgv->GetAgvId());
            MovingPayload->SetStringField(TEXT("task_id"), Order ? Order->TaskId : FString());
            MovingPayload->SetStringField(TEXT("order_id"), Order ? Order->OrderId : FString());
            MovingPayload->SetStringField(TEXT("load_id"), (Order && Order->Load) ? Order->Load->LoadId : FString());
            MovingPayload->SetStringField(TEXT("dispatch_reason"), DispatchScore.Explanation);
            MovingPayload->SetStringField(TEXT("route_segment_id"), DispatchScore.RouteSegmentId);
            MovingPayload->SetNumberField(TEXT("dispatch_score"), DispatchScore.TotalScore);
            MovingPayload->SetNumberField(TEXT("eta_seconds"), DispatchScore.EtaSeconds);
            UE_LOG(LogTemp, Log, TEXT("AGVSimController: Dispatcher selected %s for station %d: %s"),
                *TargetAgv->GetAgvId(), StationId, *DispatchScore.Explanation);
            Controller->SendChatEvent(SessionId, CorrelationId, CommandId, TEXT("robot.moving"), MovingPayload);
            return;
        }

        // Fallback (cancel_command, or no running AGV to drive): close the command now so
        // the chat turn still completes.
        TSharedPtr<FJsonObject> Payload = MakeShared<FJsonObject>();
        Payload->SetNumberField(TEXT("station_id"), StationId);
        Payload->SetStringField(TEXT("command_name"), CommandName);
        Payload->SetStringField(TEXT("reason"), bIsDriveCommand ? (DispatchScore.Explanation.IsEmpty() ? TEXT("no_available_agv_or_station") : DispatchScore.Explanation) : TEXT("non_drive_command"));
        Controller->SendChatEvent(SessionId, CorrelationId, CommandId, TEXT("robot.command.completed"), Payload);
    });

    RespondJson(OnComplete, TEXT("{\"status\":\"accepted\"}"));
    return true;
}

void AAGVSimController::OnAgvReachedStation(AAGVActor* Agv, int32 StationId)
{
    if (!IsValid(Agv))
    {
        return;
    }

    FPendingStationCommand Pending;
    if (!PendingStationCommands.RemoveAndCopyValue(Agv->GetAgvId(), Pending))
    {
        return;
    }

    PushHudEvent(FString::Printf(TEXT("%s reached station %d"), *Agv->GetAgvId(), StationId));
    const FString TaskId = Agv->GetCurrentTaskId();
    const FString OrderId = Agv->GetCurrentOrderId();
    const FString LoadId = Agv->GetCurrentLoadId();
    CompleteOrderForAgv(Agv->GetAgvId());
    if (AStationActor* Station = ResolveStation(StationId))
    {
        Station->ReleaseReservation(Agv->GetAgvId());
    }

    TSharedPtr<FJsonObject> Payload = MakeShared<FJsonObject>();
    Payload->SetNumberField(TEXT("station_id"), StationId);
    Payload->SetStringField(TEXT("agv_id"), Agv->GetAgvId());
    Payload->SetStringField(TEXT("command_name"), Pending.CommandName);
    Payload->SetStringField(TEXT("task_id"), TaskId);
    Payload->SetStringField(TEXT("order_id"), OrderId);
    Payload->SetStringField(TEXT("load_id"), LoadId);
    SendChatEvent(Pending.SessionId, Pending.CorrelationId, Pending.CommandId, TEXT("robot.command.completed"), Payload);
}

AAGVActor* AAGVSimController::ResolveCommandAgv(const FString& AgvId, AStationActor* TargetStation, FDispatchScoreBreakdown* OutScore) const
{
    if (!bRuntimeActorsInitialized)
    {
        return nullptr;
    }

    if (DispatcherActor)
    {
        FDispatchScoreBreakdown Score;
        AAGVActor* SelectedAgv = DispatcherActor->SelectAgvForStation(SpawnedAgvs, TargetStation, AgvId, Score);
        if (OutScore)
        {
            *OutScore = Score;
        }
        return SelectedAgv;
    }

    for (AAGVActor* Agv : SpawnedAgvs)
    {
        if (IsValid(Agv) && Agv->GetStateName() != TEXT("STOPPED_COLLISION"))
        {
            return Agv;
        }
    }
    return nullptr;
}

void AAGVSimController::RebuildStationRegistry()
{
    if (StationRegistry)
    {
        StationRegistry->Rebuild(AuthoredStations);
    }
}

AStationActor* AAGVSimController::ResolveStation(int32 StationId) const
{
    return StationRegistry ? StationRegistry->ResolveStation(StationId) : nullptr;
}

AStationActor* AAGVSimController::FindNearestStationOfKind(const FVector& TestLocation, EStationKind Kind, float MaxDistance) const
{
    return StationRegistry ? StationRegistry->FindNearestStationOfKind(TestLocation, Kind, MaxDistance) : nullptr;
}

void AAGVSimController::EnsureInteractionStations()
{
    if (StationRegistry)
    {
        StationRegistry->EnsureInteractionStations(AuthoredStations, AuthoredPaths, ActiveParams.AgvCount);
    }
}


UTransportOrder* AAGVSimController::CreateStationCommandOrder(int32 StationId, const FString& LoadType, int32 Priority)
{
    const FString LoadId = FString::Printf(TEXT("load_%s"), *FGuid::NewGuid().ToString(EGuidFormats::Digits));
    ULoadObject* Load = ULoadObject::Create(this, LoadId, StationId, LoadType);
    UTransportOrder* Order = UTransportOrder::CreateStationCommand(this, StationId, Load, Priority);
    ActiveLoads.Add(Load);
    ActiveOrders.Add(Order);
    return Order;
}

void AAGVSimController::CompleteOrderForAgv(const FString& AgvId)
{
    for (int32 Index = ActiveOrders.Num() - 1; Index >= 0; --Index)
    {
        UTransportOrder* Order = ActiveOrders[Index];
        if (Order && Order->AssignedAgvId == AgvId && Order->State == ETransportOrderState::Completed)
        {
            CompletedOrders.Add(Order);
            ActiveOrders.RemoveAt(Index);
        }
    }
}

bool AAGVSimController::HandleSimStatusRequest(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete)
{
    // Reading SpawnedAgvs / IntersectionManager must happen on the game thread; the
    // HTTP result callback may be invoked asynchronously, so defer the response.
    AAGVSimController* Controller = this;
    AsyncTask(ENamedThreads::GameThread, [Controller, OnComplete]()
    {
        FString Body;
        if (IsValid(Controller))
        {
            TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Body);
            FJsonSerializer::Serialize(Controller->BuildStatusJson(), Writer);
        }
        else
        {
            Body = TEXT("{\"running\":false}");
        }
        AAGVSimController::RespondJson(OnComplete, Body);
    });
    return true;
}


void AAGVSimController::SendTelemetryPayload(const TSharedRef<FJsonObject>& Json)
{
    if (Telemetry)
    {
        Telemetry->SendPayload(Json, WebSocket);
    }
}


void AAGVSimController::EmitTelemetry()
{
    if (!bSimRunning)
    {
        return;
    }

    const double NowMs = FDateTime::UtcNow().ToUnixTimestamp() * 1000.0;

    // Report every authored AGV ??active ones (in SpawnedAgvs) plus offline ones reset to
    // StoppedOperation ??so the dashboard list shows a stopped (red) entry instead of dropping the
    // unit or showing its stale previous-run telemetry.
    for (const AAGVActor* Agv : AuthoredAgvs)
    {
        if (!IsValid(Agv))
        {
            continue;
        }

        TSharedRef<FJsonObject> Json = MakeShared<FJsonObject>();
        Json->SetStringField(TEXT("kind"), TEXT("agv"));
        Json->SetStringField(TEXT("cell_id"), CellId);
        Json->SetStringField(TEXT("agv_id"), Agv->GetAgvId());
        Json->SetNumberField(TEXT("battery"), Agv->GetBatteryPercent());
        Json->SetNumberField(TEXT("speed"), Agv->GetCurrentSpeed());
        Json->SetStringField(TEXT("state"), Agv->GetStateName());
        Json->SetStringField(TEXT("task_lifecycle_state"), Agv->GetTaskLifecycleStateName());
        Json->SetStringField(TEXT("task_failure_reason"), Agv->GetTaskFailureReason());
        Json->SetBoolField(TEXT("state_tree_control_ready"), Agv->IsStateTreeControlReady());
        Json->SetStringField(TEXT("state_tree_last_operation"), Agv->GetLastStateTreeControlOperation());
        Json->SetStringField(TEXT("destination"), Agv->GetDestinationLabel());
        Json->SetBoolField(TEXT("carrying_load"), Agv->IsCarryingLoad());
        Json->SetNumberField(TEXT("completed_tasks"), Agv->GetCompletedTasks());
        Json->SetStringField(TEXT("task_id"), Agv->GetCurrentTaskId());
        Json->SetStringField(TEXT("order_id"), Agv->GetCurrentOrderId());
        Json->SetStringField(TEXT("load_id"), Agv->GetCurrentLoadId());
        Json->SetNumberField(TEXT("current_station_id"), Agv->GetCurrentStationId());
        Json->SetNumberField(TEXT("target_station_id"), Agv->GetTargetStationId());
        Json->SetStringField(TEXT("current_segment_id"), Agv->GetCurrentRouteSegmentId());
        Json->SetStringField(TEXT("reservation_state"), Agv->GetReservationState());
        Json->SetNumberField(TEXT("route_wait_seconds"), Agv->GetRouteWaitDurationSeconds());
        Json->SetNumberField(TEXT("eta_seconds"), Agv->GetTargetStationId() > 0 ? Agv->EstimateEtaToStation(ResolveStation(Agv->GetTargetStationId())) : 0.0);

        const FVector Location = Agv->GetActorLocation();
        TSharedPtr<FJsonObject> Position = MakeShared<FJsonObject>();
        Position->SetNumberField(TEXT("x"), Location.X);
        Position->SetNumberField(TEXT("y"), Location.Y);
        Position->SetNumberField(TEXT("z"), Location.Z);
        Json->SetObjectField(TEXT("position"), Position);
        Json->SetNumberField(TEXT("ts"), NowMs);

        SendTelemetryPayload(Json);
    }

    TSharedRef<FJsonObject> ProcessJson = BuildStatusJson();
    ProcessJson->SetStringField(TEXT("kind"), TEXT("process"));
    ProcessJson->SetNumberField(TEXT("ts"), NowMs);

    // HUD fields: the in-viewport HUD was removed in favour of a web overlay HUD, so the
    // process frame now carries the FVcoreHudSnapshot the dashboard renders.
    const FVcoreHudSnapshot Hud = GetHudSnapshot();
    ProcessJson->SetNumberField(TEXT("tasks_completed"), Hud.TasksCompleted);
    ProcessJson->SetNumberField(TEXT("collisions"), Hud.Collisions);
    ProcessJson->SetStringField(TEXT("policy_id"), Hud.PolicyId);
    ProcessJson->SetStringField(TEXT("verdict_summary"), Hud.VerdictSummary);
    ProcessJson->SetBoolField(TEXT("verdict_passed"), Hud.bVerdictPassed);
    TArray<TSharedPtr<FJsonValue>> RecentEventsJson;
    for (const FString& Event : Hud.RecentEvents)
    {
        RecentEventsJson.Add(MakeShared<FJsonValueString>(Event));
    }
    ProcessJson->SetArrayField(TEXT("recent_events"), RecentEventsJson);

    SendTelemetryPayload(ProcessJson);
}

void AAGVSimController::SelectViewTarget(const FString& AgvId)
{
    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }

    APlayerController* PlayerController = UGameplayStatics::GetPlayerController(World, 0);
    if (!PlayerController)
    {
        return;
    }

    if (AgvId.IsEmpty() || AgvId.Equals(TEXT("overview"), ESearchCase::IgnoreCase) || AgvId.Equals(TEXT("zone-1"), ESearchCase::IgnoreCase))
    {
        // Overview / Zone 1 == the main cell view. If a dedicated Zone 1 camera is placed +
        // tagged, pin it (suspend auto-direction); otherwise fall back to the controller's
        // own overview camera and re-enable the F3 auto-director.
        if (AActor* ZoneCam = FindZoneCamera(TEXT("Zone1")))
        {
            if (CinematicDirector)
            {
                CinematicDirector->NotifyManualOverride();
            }
            PlayerController->SetViewTargetWithBlend(ZoneCam, 0.4f);
            return;
        }
        if (RequestLoadConfiguredZoneCameraLevel(TEXT("Zone1"), AgvId.IsEmpty() ? TEXT("zone-1") : AgvId))
        {
            return;
        }
        if (CinematicDirector)
        {
            CinematicDirector->SetEnabled(true);
        }
        PlayerController->SetViewTargetWithBlend(this, 0.4f);
        return;
    }

    // Zone 2 / Zone 3 map to authored camera actors tagged "Zone2" / "Zone3".
    if (AgvId.Equals(TEXT("zone-2"), ESearchCase::IgnoreCase) || AgvId.Equals(TEXT("zone-3"), ESearchCase::IgnoreCase))
    {
        const FName ZoneTag = AgvId.Equals(TEXT("zone-2"), ESearchCase::IgnoreCase) ? TEXT("Zone2") : TEXT("Zone3");
        if (AActor* ZoneCam = FindZoneCamera(ZoneTag))
        {
            if (CinematicDirector)
            {
                CinematicDirector->NotifyManualOverride();
            }
            PlayerController->SetViewTargetWithBlend(ZoneCam, 0.4f);
            return;
        }
        if (RequestLoadConfiguredZoneCameraLevel(ZoneTag, AgvId))
        {
            return;
        }
        UE_LOG(LogTemp, Warning, TEXT("AGVSimController: No camera tagged %s for %s"), *ZoneTag.ToString(), *AgvId);
        return;
    }

    for (AAGVActor* Agv : SpawnedAgvs)
    {
        if (IsValid(Agv) && Agv->GetAgvId().Equals(AgvId, ESearchCase::IgnoreCase))
        {
            // A manual AGV selection suspends auto-direction until overview is reselected.
            if (CinematicDirector)
            {
                CinematicDirector->NotifyManualOverride();
            }
            PlayerController->SetViewTargetWithBlend(Agv, 0.4f);
            return;
        }
    }

    UE_LOG(LogTemp, Warning, TEXT("AGVSimController: Camera select for unknown AGV %s"), *AgvId);
}

AActor* AAGVSimController::FindZoneCamera(const FName& ZoneTag) const
{
    UWorld* World = GetWorld();
    if (!World)
    {
        return nullptr;
    }

    const auto IsCameraTarget = [](const AActor* Actor) -> bool
    {
        return IsValid(Actor)
            && (Actor->IsA<ACameraActor>() || Actor->FindComponentByClass<UCameraComponent>() != nullptr);
    };

    const FName Zone1Tag(TEXT("Zone1"));
    const FName Zone2Tag(TEXT("Zone2"));
    const FName Zone3Tag(TEXT("Zone3"));
    const TSoftObjectPtr<AActor>* ConfiguredCameraRef =
        ZoneTag == Zone1Tag ? &Zone1CameraTarget
        : ZoneTag == Zone2Tag ? &Zone2CameraTarget
        : ZoneTag == Zone3Tag ? &Zone3CameraTarget
        : nullptr;
    AActor* const ConfiguredCamera = ConfiguredCameraRef ? ConfiguredCameraRef->Get() : nullptr;

    if (ConfiguredCamera)
    {
        if (IsCameraTarget(ConfiguredCamera))
        {
            return ConfiguredCamera;
        }

        UE_LOG(LogTemp, Warning, TEXT("AGVSimController: Configured camera target '%s' for '%s' has no camera component."), *ConfiguredCamera->GetName(), *ZoneTag.ToString());
        return nullptr;
    }
    if (ConfiguredCameraRef && !ConfiguredCameraRef->IsNull())
    {
        UE_LOG(LogTemp, Warning, TEXT("AGVSimController: Configured camera target for '%s' is assigned but not loaded; falling back to tag lookup."), *ZoneTag.ToString());
    }

    // Accept any of: an actor Tag, a tag placed on the camera component (a common mistake),
    // the internal actor name, or the editor outliner label containing the zone tag. The
    // scan is only a compatibility fallback when no explicit Zone camera target is assigned.
    const FString TagString = ZoneTag.ToString();
    int32 ActorCount = 0;
    int32 CameraCandidateCount = 0;
    for (TActorIterator<AActor> It(World); It; ++It)
    {
        AActor* Actor = *It;
        if (!IsValid(Actor))
        {
            continue;
        }
        ++ActorCount;

        const bool bIsCameraTarget = IsCameraTarget(Actor);
        if (bIsCameraTarget)
        {
            ++CameraCandidateCount;
        }

        bool bZoneMatch = Actor->Tags.Contains(ZoneTag);
        for (const UActorComponent* Comp : Actor->GetComponents())
        {
            if (Comp && Comp->ComponentTags.Contains(ZoneTag))
            {
                bZoneMatch = true;
                break;
            }
        }

        // FString::Contains is case-insensitive by default.
        if (Actor->GetName().Contains(TagString))
        {
            bZoneMatch = true;
        }
#if WITH_EDITOR
        if (Actor->GetActorLabel().Contains(TagString))
        {
            bZoneMatch = true;
        }
#endif

        if (bZoneMatch)
        {
            if (bIsCameraTarget)
            {
                return Actor;
            }

            UE_LOG(LogTemp, Warning, TEXT("AGVSimController: Actor '%s' matches zone tag '%s' but has no camera component."), *Actor->GetName(), *TagString);
        }
    }

    UE_LOG(LogTemp, Warning, TEXT("AGVSimController: FindZoneCamera no match for '%s' among %d actor(s), %d camera candidate(s). Check actor/component Tags, loaded level/World Partition state, or outliner name."), *TagString, ActorCount, CameraCandidateCount);
    return nullptr;
}

bool AAGVSimController::RequestLoadConfiguredZoneCameraLevel(const FName& ZoneTag, const FString& AgvId)
{
    const FName Zone1Tag(TEXT("Zone1"));
    const FName Zone2Tag(TEXT("Zone2"));
    const FName Zone3Tag(TEXT("Zone3"));
    const TSoftObjectPtr<AActor>* ConfiguredCameraRef =
        ZoneTag == Zone1Tag ? &Zone1CameraTarget
        : ZoneTag == Zone2Tag ? &Zone2CameraTarget
        : ZoneTag == Zone3Tag ? &Zone3CameraTarget
        : nullptr;

    if (!ConfiguredCameraRef || ConfiguredCameraRef->IsNull() || ConfiguredCameraRef->Get())
    {
        return false;
    }

    UWorld* World = GetWorld();
    if (!World)
    {
        return false;
    }

    const FSoftObjectPath CameraPath = ConfiguredCameraRef->ToSoftObjectPath();
    const FString LevelPackageName = CameraPath.GetLongPackageName();
    if (LevelPackageName.IsEmpty())
    {
        UE_LOG(LogTemp, Warning, TEXT("AGVSimController: Configured camera target for '%s' has an invalid soft path '%s'."), *ZoneTag.ToString(), *CameraPath.ToString());
        return false;
    }

    FLatentActionInfo LatentInfo;
    LatentInfo.CallbackTarget = this;
    UGameplayStatics::LoadStreamLevel(World, FName(*LevelPackageName), true, false, LatentInfo);

    UE_LOG(LogTemp, Log, TEXT("AGVSimController: Requested streaming level '%s' for configured camera target '%s' (%s)."), *LevelPackageName, *ZoneTag.ToString(), *CameraPath.ToString());

    FTimerHandle RetryHandle;
    World->GetTimerManager().SetTimer(
        RetryHandle,
        FTimerDelegate::CreateWeakLambda(this, [this, AgvId]()
        {
            SelectViewTarget(AgvId);
        }),
        0.25f,
        false);

    return true;
}

bool AAGVSimController::HandleCameraSelectRequest(const FHttpServerRequest& Request, const FHttpResultCallback& OnComplete)
{
    TSharedPtr<FJsonObject> Json = ParseRequestBody(Request);
    if (!Json.IsValid())
    {
        OnComplete(FHttpServerResponse::Error(EHttpServerResponseCodes::BadRequest, TEXT(""), TEXT("Invalid JSON")));
        return true;
    }
    const TSharedPtr<FJsonObject>* ParamsObjPtr = nullptr;
    Json->TryGetObjectField(TEXT("parameters"), ParamsObjPtr);
    const TSharedPtr<FJsonObject> ParamsObj = (ParamsObjPtr && ParamsObjPtr->IsValid()) ? *ParamsObjPtr : Json;

    FString AgvId;
    if (!ParamsObj->TryGetStringField(TEXT("agv_id"), AgvId))
    {
        Json->TryGetStringField(TEXT("agv_id"), AgvId);
    }

    AAGVSimController* Controller = this;
    AsyncTask(ENamedThreads::GameThread, [Controller, AgvId]()
    {
        if (IsValid(Controller))
        {
            Controller->SelectViewTarget(AgvId);
        }
    });

    RespondJson(OnComplete, FString::Printf(TEXT("{\"status\":\"accepted\",\"agv_id\":\"%s\"}"), *AgvId));
    return true;
}
