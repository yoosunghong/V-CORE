#include "AGVActor.h"

#include "AGVMovementComponent.h"
#include "AGVNameplateWidget.h"
#include "AGVStateHelpers.h"
#include "AGVTaskComponent.h"
#include "AGVTaskRunnerComponent.h"
#include "AGVPathActor.h"
#include "AGVSimController.h"
#include "IntersectionManager.h"
#include "LoadObject.h"
#include "SimEventBus.h"
#include "StationActor.h"
#include "TrafficManagerActor.h"
#include "TransportOrder.h"
#include "Camera/PlayerCameraManager.h"
#include "Camera/CameraComponent.h"
#include "Components/SceneComponent.h"
#include "Components/SphereComponent.h"
#include "Components/SplineComponent.h"
#include "Components/WidgetComponent.h"
#include "Engine/CollisionProfile.h"
#include "Engine/World.h"
#include "GameFramework/SpringArmComponent.h"
#include "GameFramework/PlayerController.h"

AAGVActor::AAGVActor()
{
    PrimaryActorTick.bCanEverTick = true;

    // Now an APawn (so the humanoid locomotion AnimBP's TryGetPawnOwner→GetVelocity path works),
    // but it is driven kinematically along a spline — never possessed and never AI-controlled.
    AIControllerClass = nullptr;
    AutoPossessAI = EAutoPossessAI::Disabled;
    AutoPossessPlayer = EAutoReceiveInput::Disabled;

    SceneRoot = CreateDefaultSubobject<USceneComponent>(TEXT("SceneRoot"));
    SetRootComponent(SceneRoot);

    CollisionComponent = CreateDefaultSubobject<USphereComponent>(TEXT("CollisionComponent"));
    CollisionComponent->SetupAttachment(SceneRoot);
    CollisionComponent->SetSphereRadius(100.0f);
    // Use Pawn profile but override the Pawn channel to Overlap so AGV-to-AGV
    // proximity fires OnComponentBeginOverlap (Pawn profile defaults to Block).
    CollisionComponent->SetCollisionProfileName(UCollisionProfile::Pawn_ProfileName);
    CollisionComponent->SetCollisionResponseToChannel(ECC_Pawn, ECR_Overlap);
    CollisionComponent->SetGenerateOverlapEvents(true);
    CollisionComponent->OnComponentBeginOverlap.AddDynamic(this, &AAGVActor::OnOverlapBegin);

    CameraBoom = CreateDefaultSubobject<USpringArmComponent>(TEXT("CameraBoom"));
    CameraBoom->SetupAttachment(SceneRoot);
    CameraBoom->TargetArmLength = 320.0f;
    CameraBoom->SocketOffset = FVector(0.0f, 0.0f, 140.0f);
    CameraBoom->bUsePawnControlRotation = false;
    CameraBoom->bDoCollisionTest = false;

    ViewpointCamera = CreateDefaultSubobject<UCameraComponent>(TEXT("ViewpointCamera"));
    ViewpointCamera->SetupAttachment(CameraBoom, USpringArmComponent::SocketName);
    ViewpointCamera->SetRelativeRotation(FRotator(-12.0f, 0.0f, 0.0f));

    // F2 — status billboard; tracks this AGV automatically (see its BeginPlay).
    NameplateWidgetComponent = CreateDefaultSubobject<UWidgetComponent>(TEXT("NameplateWidget"));
    NameplateWidgetComponent->SetupAttachment(SceneRoot);
    NameplateWidgetComponent->SetRelativeLocation(FVector(0.0f, 0.0f, 150.0f));
    NameplateWidgetComponent->SetWidgetSpace(EWidgetSpace::Screen);
    NameplateWidgetComponent->SetDrawSize(FVector2D(260.0f, 90.0f));
    NameplateWidgetComponent->SetPivot(FVector2D(0.5f, 0.5f));
    NameplateWidgetComponent->SetCollisionEnabled(ECollisionEnabled::NoCollision);
    NameplateWidgetComponent->SetTwoSided(true);

    MovementComponent = CreateDefaultSubobject<UAGVMovementComponent>(TEXT("MovementComponent"));
    TaskComponent = CreateDefaultSubobject<UAGVTaskComponent>(TEXT("TaskComponent"));
    if (TaskComponent)
    {
        TaskComponent->bRequireStateTreeForControl = false;
    }
    TaskRunnerComponent = CreateDefaultSubobject<UAGVTaskRunnerComponent>(TEXT("TaskRunnerComponent"));
}

void AAGVActor::BeginPlay()
{
    Super::BeginPlay();

    AuthoredTransform = GetActorTransform();
    InitializeNameplateWidget();
}

void AAGVActor::Tick(float DeltaSeconds)
{
    Super::Tick(DeltaSeconds);

    FaceNameplateToCamera();

    if (!bRunActive)
    {
        return;
    }

    if (IsActiveState(State))
    {
        ActiveTimeSeconds += DeltaSeconds;
    }

    UpdateActionState(DeltaSeconds);
    UpdateMovement(DeltaSeconds);
    CheckAutonomousStationArrival();

    // Keep the nameplate battery gauge live as the charge drains during the run.
    UpdateNameplateWidget();
}

void AAGVActor::Configure(
    AAGVSimController* InController,
    AIntersectionManager* InIntersectionManager,
    ATrafficManagerActor* InTrafficManager,
    AAGVPathActor* InPathActor,
    const FString& InAgvId,
    float InInitialDistance,
    float InSimSpeed,
    float InBottleneckThresholdSec)
{
    Controller = InController;
    AgvId = InAgvId;
    InitialDistance = InInitialDistance;
    // Start the approach from the placed home pose so the drive-to-path is deterministic and never
    // begins from wherever a previous run left the AGV.
    SetActorTransform(AuthoredTransform);
    CompletedTasks = 0;
    ActiveTimeSeconds = 0.0;
    bCarryingLoad = false;
    bHasTaskAssigned = false;
    CurrentOrder = nullptr;
    TargetStation = nullptr;
    CurrentStationId = 0;
    TargetStationId = 0;
    if (MovementComponent)
    {
        MovementComponent->Configure(
            InController,
            InIntersectionManager,
            InTrafficManager,
            InPathActor,
            InInitialDistance,
            InSimSpeed,
            InBottleneckThresholdSec);
    }
    if (TaskComponent)
    {
        // A freshly spawned task component is already Offline with no order, and its StateTree
        // control isn't started until StartRun. Calling StopRun here only emits "blocked …
        // StateTree not running" warnings for a no-op reset, so just bind the component.
        TaskComponent->BindStateTreeComponent(nullptr);
    }

    UpdateNameplateWidget();
}

void AAGVActor::StartRun()
{
    const double SimTimestamp = Controller ? Controller->GetSimTimestampSeconds() : 0.0;
    if (TaskComponent)
    {
        TaskComponent->BindStateTreeComponent(nullptr);
        if (!TaskComponent->ResetForRun(AgvId, SimTimestamp))
        {
            bRunActive = false;
            if (MovementComponent)
            {
                MovementComponent->StopMovement();
            }
            UpdateNameplateWidget();
            return;
        }
    }

    bRunActive = true;
    if (MovementComponent)
    {
        MovementComponent->StartRun();
    }
    if (TaskRunnerComponent)
    {
        TaskRunnerComponent->ResetForRun();
    }
    TransitionTo(EAGVState::Idle);
}

void AAGVActor::StopRun()
{
    bRunActive = false;
    if (MovementComponent)
    {
        MovementComponent->StopMovement();
    }
    if (TaskComponent)
    {
        TaskComponent->StopRun(Controller ? Controller->GetSimTimestampSeconds() : 0.0);
    }
    UpdateNameplateWidget();
}

void AAGVActor::ResetToStoppedOperation(const FString& InAgvId)
{
    // An offline AGV's TaskComponent is already stopped (prior run's teardown calls StopRun), so we
    // reset state directly rather than via StopRun() — that would re-stop the component and log a
    // spurious "StateTree not running" warning.
    bRunActive = false;
    AgvId = InAgvId;

    // Restore the home pose so the dashboard never shows last run's position.
    SetActorTransform(AuthoredTransform);

    // Clear every per-run field so battery/task/load read as a fresh, idle unit.
    if (MovementComponent)
    {
        MovementComponent->ResetForOffline();
        MovementComponent->ClearManagers();
    }
    if (TaskRunnerComponent)
    {
        TaskRunnerComponent->ResetForRun();
    }
    ActiveTimeSeconds = 0.0;
    CompletedTasks = 0;
    bCarryingLoad = false;
    bHasTaskAssigned = false;
    CurrentOrder = nullptr;
    TargetStation = nullptr;
    CurrentStationId = 0;
    TargetStationId = 0;

    // Set directly (not TransitionTo): an offline AGV has no live TaskComponent lifecycle to drive
    // and must emit no state-change event.
    State = EAGVState::StoppedOperation;
    UpdateNameplateWidget();
}

bool AAGVActor::AssignDeliveryTask(UTransportOrder* Order)
{
    if (TaskComponent && !TaskComponent->AssignOrder(Order, 0, Controller ? Controller->GetSimTimestampSeconds() : 0.0))
    {
        return false;
    }

    bHasTaskAssigned = true;
    CurrentOrder = Order;
    if (CurrentOrder)
    {
        CurrentOrder->AssignToAgv(AgvId);
        CurrentOrder->MarkInProgress();
    }
    bCarryingLoad = false;
    CurrentTaskStartedAt = Controller ? Controller->GetSimTimestampSeconds() : 0.0;
    TransitionTo(EAGVState::MovingToPickup);
    return State == EAGVState::MovingToPickup;
}

bool AAGVActor::DirectToStation(AStationActor* Station, UTransportOrder* Order)
{
    if (!bRunActive || State == EAGVState::StoppedCollision || !IsValid(Station))
    {
        return false;
    }

    if (TaskComponent && !TaskComponent->AssignOrder(Order, Station->GetStationId(), Controller ? Controller->GetSimTimestampSeconds() : 0.0))
    {
        return false;
    }

    TargetStation = Station;
    TargetStationId = Station->GetStationId();
    CurrentOrder = Order;
    if (CurrentOrder)
    {
        CurrentOrder->AssignToAgv(AgvId);
        CurrentOrder->MarkInProgress();
        if (CurrentOrder->Load)
        {
            CurrentOrder->Load->MarkHeldByAgv(AgvId);
            bCarryingLoad = true;
        }
    }
    if (MovementComponent)
    {
        MovementComponent->SetStationTargetDistance(FindDistanceClosestToWorldLocation(Station->GetDockingTransform().GetLocation()));
        MovementComponent->ResetRouteReservationState();
    }
    TransitionTo(EAGVState::MovingToStation);
    return State == EAGVState::MovingToStation;
}

void AAGVActor::ForceCollisionStop(AAGVActor* OtherAgv)
{
    if (State == EAGVState::StoppedCollision)
    {
        return;
    }

    if (CurrentOrder)
    {
        CurrentOrder->MarkFailed(TEXT("collision_stop"));
    }
    if (TaskComponent)
    {
        if (!TaskComponent->FailCurrentTask(TEXT("collision_stop"), Controller ? Controller->GetSimTimestampSeconds() : 0.0))
        {
            return;
        }
    }
    TransitionTo(EAGVState::StoppedCollision);

    if (Controller && IsValid(OtherAgv) && AgvId < OtherAgv->GetAgvId())
    {
        if (USimEventBus* Bus = USimEventBus::Get(this))
        {
            FSimCollisionEvent CollisionEvent;
            CollisionEvent.AgvIdA = AgvId;
            CollisionEvent.AgvIdB = OtherAgv->GetAgvId();
            CollisionEvent.Position = (GetActorLocation() + OtherAgv->GetActorLocation()) * 0.5f;
            CollisionEvent.RelativeVelocity = FMath::Abs(GetCurrentSpeed() - OtherAgv->GetCurrentSpeed());
            Bus->BroadcastCollision(CollisionEvent);
        }
    }
}

FVector AAGVActor::GetVelocity() const
{
    return GetActorForwardVector() * GetCurrentSpeed();
}

float AAGVActor::GetCurrentSpeed() const
{
    return MovementComponent ? MovementComponent->GetCurrentSpeed() : 0.0f;
}

float AAGVActor::GetBatteryPercent() const
{
    return MovementComponent ? MovementComponent->GetBatteryPercent() : 0.0f;
}

FString AAGVActor::GetStateName() const
{
    return FAGVStateHelpers::ToStateString(State);
}

FString AAGVActor::GetDestinationLabel() const
{
    switch (State)
    {
    case EAGVState::MovingToPickup:
    case EAGVState::Loading:
        return TEXT("Pickup Dock");
    case EAGVState::MovingToDropoff:
    case EAGVState::Unloading:
        return TEXT("Dropoff Station");
    case EAGVState::WaitingAtSection:
        return TEXT("Intersection");
    case EAGVState::MovingToStation:
        return FString::Printf(TEXT("Station %d"), TargetStationId);
    case EAGVState::StoppedCollision:
        return TEXT("Halted");
    case EAGVState::StoppedOperation:
        return TEXT("Stopped");
    default:
        return TEXT("Idle");
    }
}

FString AAGVActor::GetCurrentTaskId() const
{
    return CurrentOrder ? CurrentOrder->TaskId : FString();
}

FString AAGVActor::GetCurrentOrderId() const
{
    return CurrentOrder ? CurrentOrder->OrderId : FString();
}

FString AAGVActor::GetCurrentLoadId() const
{
    return (CurrentOrder && CurrentOrder->Load) ? CurrentOrder->Load->LoadId : FString();
}

bool AAGVActor::IsAvailableForDispatch() const
{
    return bRunActive && State == EAGVState::Idle && !HasActiveAssignment();
}

bool AAGVActor::RequestStateTreeState(EAGVState RequestedState)
{
    if (!bRunActive && RequestedState != EAGVState::Idle)
    {
        return false;
    }

    switch (RequestedState)
    {
    case EAGVState::MovingToPickup:
    case EAGVState::MovingToDropoff:
    case EAGVState::MovingToStation:
    case EAGVState::Loading:
    case EAGVState::Unloading:
    case EAGVState::Idle:
        TransitionTo(RequestedState);
        return State == RequestedState;
    default:
        return false;
    }
}

bool AAGVActor::CompleteStateTreeOrder()
{
    const double SimTimestamp = Controller ? Controller->GetSimTimestampSeconds() : 0.0;

    if (CurrentOrder)
    {
        CurrentOrder->MarkCompleted();
    }

    if (TaskComponent && !TaskComponent->CompleteCurrentTask(SimTimestamp))
    {
        return false;
    }

    bCarryingLoad = false;
    bHasTaskAssigned = false;
    TargetStation = nullptr;
    TargetStationId = 0;
    CurrentOrder = nullptr;
    TransitionTo(EAGVState::Idle);
    return State == EAGVState::Idle;
}

bool AAGVActor::FailStateTreeOrder(const FString& FailureReason)
{
    const FString EffectiveReason = FailureReason.IsEmpty() ? TEXT("state_tree_failed") : FailureReason;
    if (CurrentOrder)
    {
        CurrentOrder->MarkFailed(EffectiveReason);
    }

    if (TaskComponent && !TaskComponent->FailCurrentTask(EffectiveReason, Controller ? Controller->GetSimTimestampSeconds() : 0.0))
    {
        return false;
    }

    bHasTaskAssigned = false;
    if (MovementComponent)
    {
        MovementComponent->StopMovement();
    }
    TransitionTo(EAGVState::StoppedCollision);
    return State == EAGVState::StoppedCollision;
}

float AAGVActor::EstimateTravelDistanceToStation(const AStationActor* Station) const
{
    return MovementComponent ? MovementComponent->EstimateTravelDistanceToStation(Station) : 0.0f;
}

float AAGVActor::EstimateEtaToStation(const AStationActor* Station) const
{
    return MovementComponent ? MovementComponent->EstimateEtaToStation(Station) : 0.0f;
}

FString AAGVActor::GetCurrentRouteSegmentId() const
{
    return MovementComponent ? MovementComponent->GetCurrentRouteSegmentId() : FString();
}

FString AAGVActor::GetReservationState() const
{
    return MovementComponent ? MovementComponent->GetReservationState(State) : TEXT("unreserved");
}

double AAGVActor::GetRouteWaitDurationSeconds() const
{
    return MovementComponent ? MovementComponent->GetRouteWaitDurationSeconds() : 0.0;
}

FString AAGVActor::GetTaskLifecycleStateName() const
{
    return TaskComponent ? TaskComponent->GetLifecycleStateName() : GetStateName();
}

FString AAGVActor::GetTaskFailureReason() const
{
    return TaskComponent ? TaskComponent->GetFailureReason() : FString();
}

bool AAGVActor::IsStateTreeControlReady() const
{
    return TaskComponent && TaskComponent->IsStateTreeControlReady();
}

FString AAGVActor::GetLastStateTreeControlOperation() const
{
    return TaskComponent ? TaskComponent->GetLastControlOperation() : FString();
}

void AAGVActor::OnOverlapBegin(
    UPrimitiveComponent* OverlappedComponent,
    AActor* OtherActor,
    UPrimitiveComponent* OtherComp,
    int32 OtherBodyIndex,
    bool bFromSweep,
    const FHitResult& SweepResult)
{
    if (!bRunActive)
    {
        return;
    }

    AAGVActor* OtherAgv = Cast<AAGVActor>(OtherActor);
    if (!IsValid(OtherAgv) || OtherAgv == this)
    {
        return;
    }

    // A parked offline AGV (excluded from this run) is collision-inert — overlapping it must not
    // register a collision or flip it into StoppedCollision.
    if (OtherAgv->IsInState(EAGVState::StoppedOperation))
    {
        return;
    }

    ForceCollisionStop(OtherAgv);
    OtherAgv->ForceCollisionStop(this);
}

void AAGVActor::UpdateMovement(float DeltaSeconds)
{
    if (MovementComponent)
    {
        MovementComponent->TickMovement(DeltaSeconds, State, AgvId);
    }
}

void AAGVActor::UpdateActionState(float DeltaSeconds)
{
    if (TaskRunnerComponent)
    {
        TaskRunnerComponent->TickTask(DeltaSeconds, State);
    }
}

void AAGVActor::TransitionTo(EAGVState NewState)
{
    if (State == NewState)
    {
        return;
    }

    const FString PreviousState = FAGVStateHelpers::ToStateString(State);
    const FString CurrentState = FAGVStateHelpers::ToStateString(NewState);

    if (TaskComponent)
    {
        if (!TaskComponent->TransitionTo(
            FAGVStateHelpers::ToTaskLifecycleState(NewState),
            Controller ? Controller->GetSimTimestampSeconds() : 0.0,
            CurrentState))
        {
            return;
        }
    }

    State = NewState;
    if (TaskRunnerComponent)
    {
        TaskRunnerComponent->OnStateChanged(State);
    }
    if (State == EAGVState::Idle && MovementComponent)
    {
        MovementComponent->StopMovement();
    }

    if (Controller)
    {
        if (USimEventBus* Bus = USimEventBus::Get(this))
        {
            FSimAgvStateChangedEvent StateEvent;
            StateEvent.AgvId = AgvId;
            StateEvent.FromState = PreviousState;
            StateEvent.ToState = CurrentState;
            StateEvent.Speed = GetCurrentSpeed();
            StateEvent.Battery = GetBatteryPercent();
            Bus->BroadcastAgvStateChanged(StateEvent);
        }
    }

    UpdateNameplateWidget();
}

void AAGVActor::HandleStationArrival(AStationActor* Station)
{
    if (!bRunActive || !IsValid(Station))
    {
        return;
    }

    // Autonomous Load/Unload is driven by which kind of station the AGV physically reached, not by a
    // spline position. Generic stations carry no autonomous action (they exist for the commanded
    // MovingToStation path, which arrives via its own docking checkpoint below).
    if (State == EAGVState::MovingToPickup && !bCarryingLoad && Station->StationKind == EStationKind::Pickup)
    {
        CurrentStationId = Station->GetStationId();
        TransitionTo(EAGVState::Loading);
    }
    else if (State == EAGVState::MovingToDropoff && bCarryingLoad && Station->StationKind == EStationKind::Dropoff)
    {
        CurrentStationId = Station->GetStationId();
        TransitionTo(EAGVState::Unloading);
    }
}

void AAGVActor::CheckAutonomousStationArrival()
{
    if (!Controller)
    {
        return;
    }

    // Deterministic fallback for the proximity trigger: the physics overlap on a station's
    // UStationInteractionComponent is the primary arrival path, but whether it fires depends on the
    // project's Pawn collision-channel responses. A distance check against the registered stations
    // guarantees the Load/Unload cycle (and therefore the run KPIs) completes regardless. Routes
    // through the same HandleStationArrival, which is state-guarded, so the two paths never
    // double-process the same arrival.
    EStationKind DesiredKind = EStationKind::Pickup;
    if (State == EAGVState::MovingToPickup && !bCarryingLoad)
    {
        DesiredKind = EStationKind::Pickup;
    }
    else if (State == EAGVState::MovingToDropoff && bCarryingLoad)
    {
        DesiredKind = EStationKind::Dropoff;
    }
    else
    {
        return;
    }

    // Mirror the interaction sphere radius (250) plus the AGV's own collision sphere (45).
    constexpr float ArrivalRadius = 295.0f;
    if (AStationActor* Station = Controller->FindNearestStationOfKind(GetActorLocation(), DesiredKind, ArrivalRadius))
    {
        HandleStationArrival(Station);
    }
}

void AAGVActor::HandleCheckpointTransitions()
{
    // Only the commanded MovingToStation path still uses a spline-distance checkpoint (it docks at a
    // specific authored station's location). Autonomous pickup/dropoff is overlap-driven — see
    // HandleStationArrival.
    if (State != EAGVState::MovingToStation)
    {
        return;
    }

    if (MovementComponent && MovementComponent->WasLastMoveAcrossDistance(MovementComponent->GetStationTargetDistance()))
    {
        CurrentStationId = TargetStationId;
        const int32 ReachedStationId = TargetStationId;
        if (CurrentOrder)
        {
            if (CurrentOrder->Load)
            {
                CurrentOrder->Load->MarkDeliveredToStation(TargetStationId);
            }
            CurrentOrder->MarkCompleted();
        }
        if (TaskComponent)
        {
            if (!TaskComponent->CompleteCurrentTask(Controller ? Controller->GetSimTimestampSeconds() : 0.0))
            {
                return;
            }
        }
        bCarryingLoad = false;
        bHasTaskAssigned = false;
        TargetStation = nullptr;
        TargetStationId = 0;
        TransitionTo(EAGVState::Idle);
        if (Controller)
        {
            Controller->OnAgvReachedStation(this, ReachedStationId);
        }
        CurrentOrder = nullptr;
    }
}

void AAGVActor::InitializeNameplateWidget()
{
    UpdateNameplateWidget();
}

void AAGVActor::UpdateNameplateWidget()
{
    if (!NameplateWidgetComponent)
    {
        return;
    }

    UAGVNameplateWidget* NameplateWidget = Cast<UAGVNameplateWidget>(NameplateWidgetComponent->GetUserWidgetObject());
    if (!NameplateWidget)
    {
        return;
    }

    const FString NameplateName = FString::Printf(TEXT("%s %s"), *AGVDisplayName, *AgvId);
    // Task = live state label; bOnline = running (green "Online") vs stopped (red "Offline");
    // battery fills the nameplate gauge.
    NameplateWidget->SetAGVInfo(NameplateName, GetStateName(), bRunActive, GetBatteryPercent());
}

void AAGVActor::FaceNameplateToCamera()
{
    if (!bFaceNameplateToCameraInWorldSpace || !NameplateWidgetComponent
        || NameplateWidgetComponent->GetWidgetSpace() != EWidgetSpace::World)
    {
        return;
    }

    UWorld* World = GetWorld();
    if (!World)
    {
        return;
    }

    APlayerController* PlayerController = World->GetFirstPlayerController();
    if (!PlayerController || !PlayerController->PlayerCameraManager)
    {
        return;
    }

    const FVector ToCamera = PlayerController->PlayerCameraManager->GetCameraLocation() - NameplateWidgetComponent->GetComponentLocation();
    if (ToCamera.IsNearlyZero())
    {
        return;
    }

    NameplateWidgetComponent->SetWorldRotation(ToCamera.Rotation());
}

bool AAGVActor::IsActiveState(EAGVState InState) const
{
    return FAGVStateHelpers::IsActiveState(InState);
}

USplineComponent* AAGVActor::GetPathSpline() const
{
    return MovementComponent ? MovementComponent->GetPathSpline() : nullptr;
}

float AAGVActor::GetPathLength() const
{
    return MovementComponent ? MovementComponent->GetPathLength() : 1.0f;
}

float AAGVActor::FindDistanceClosestToWorldLocation(const FVector& WorldLocation) const
{
    return MovementComponent ? MovementComponent->FindDistanceClosestToWorldLocation(WorldLocation) : 0.0f;
}
