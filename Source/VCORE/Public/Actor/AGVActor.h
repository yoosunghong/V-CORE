#pragma once

#include "CoreMinimal.h"
#include "AGVTypes.h"
#include "GameFramework/Pawn.h"
#include "AGVActor.generated.h"

class AAGVSimController;
class AAGVPathActor;
class AIntersectionManager;
class AStationActor;
class ATrafficManagerActor;
class UAGVMovementComponent;
class UAGVTaskComponent;
class UAGVTaskRunnerComponent;
class UTransportOrder;
class UAGVNameplateWidget;
class UCameraComponent;
class UPrimitiveComponent;
class USceneComponent;
class USphereComponent;
class USpringArmComponent;
class USplineComponent;
class UWidgetComponent;

UCLASS()
class VCORE_API AAGVActor : public APawn
{
    GENERATED_BODY()
    friend class UAGVMovementComponent;
    friend class UAGVTaskRunnerComponent;

public:
    AAGVActor();

    virtual void BeginPlay() override;
    virtual void Tick(float DeltaSeconds) override;

    // The AGV moves procedurally via SetActorLocation, so the engine's default velocity
    // (driven by a movement component) stays zero and the skeletal-mesh AnimBP never sees
    // motion. Report a real world velocity derived from the current speed + facing so a
    // standard locomotion graph ("GetOwningActor → GetVelocity") plays the drive animation.
    virtual FVector GetVelocity() const override;

    void Configure(
        AAGVSimController* InController,
        AIntersectionManager* InIntersectionManager,
        ATrafficManagerActor* InTrafficManager,
        AAGVPathActor* InPathActor,
        const FString& InAgvId,
        float InInitialDistance,
        float InSimSpeed,
        float InBottleneckThresholdSec);

    void StartRun();
    void StopRun();
    // Reset an offline AGV (one excluded from the run) to a clean baseline: home pose, full
    // battery, no task/order, state = StoppedOperation. Keeps it visible to the dashboard as a
    // "stopped operation" entry instead of leaking last run's position/battery.
    void ResetToStoppedOperation(const FString& InAgvId);
    bool AssignDeliveryTask(UTransportOrder* Order = nullptr);
    void ForceCollisionStop(AAGVActor* OtherAgv);

    // Retarget this AGV to an authored station docking pose. Drives the AGV there using
    // the current spline follower; on arrival it returns to Idle and notifies the controller.
    bool DirectToStation(AStationActor* Station, UTransportOrder* Order);

    // Called by a station's UStationInteractionComponent when this AGV overlaps it. Drives
    // Load/Unload off the station's EStationKind (replaces the old hardcoded spline-ratio pickup/
    // dropoff checkpoints). No-op unless the AGV is in the matching MovingToPickup/MovingToDropoff state.
    void HandleStationArrival(AStationActor* Station);

    FString GetAgvId() const { return AgvId; }
    int32 GetCompletedTasks() const { return CompletedTasks; }
    double GetActiveTimeSeconds() const { return ActiveTimeSeconds; }
    bool IsCarryingLoad() const { return bCarryingLoad; }

    // Locomotion state exposed to the AGV Animation Blueprint so it can drive the
    // idle/drive blend without a movement component.
    UFUNCTION(BlueprintPure, Category="VCORE|AGV")
    float GetCurrentSpeed() const;

    UFUNCTION(BlueprintPure, Category="VCORE|AGV")
    bool IsMoving() const { return GetCurrentSpeed() > KINDA_SMALL_NUMBER; }

    float GetBatteryPercent() const;

    UFUNCTION(BlueprintPure, Category="VCORE|AGV")
    FString GetStateName() const;
    // Human-readable next destination, derived from the current movement state.
    FString GetDestinationLabel() const;
    FString GetCurrentTaskId() const;
    FString GetCurrentOrderId() const;
    FString GetCurrentLoadId() const;
    int32 GetCurrentStationId() const { return CurrentStationId; }
    int32 GetTargetStationId() const { return TargetStationId; }
    bool IsAvailableForDispatch() const;
    bool HasActiveAssignment() const { return State != EAGVState::Idle || bHasTaskAssigned || TargetStation != nullptr; }
    bool IsInState(EAGVState QueryState) const { return State == QueryState; }
    bool IsWaitingForRoute() const { return State == EAGVState::WaitingAtSection; }
    bool RequestStateTreeState(EAGVState RequestedState);
    bool CompleteStateTreeOrder();
    bool FailStateTreeOrder(const FString& FailureReason);
    float EstimateTravelDistanceToStation(const AStationActor* Station) const;
    float EstimateEtaToStation(const AStationActor* Station) const;
    FString GetCurrentRouteSegmentId() const;
    FString GetReservationState() const;
    double GetRouteWaitDurationSeconds() const;
    FString GetTaskLifecycleStateName() const;
    FString GetTaskFailureReason() const;
    bool IsStateTreeControlReady() const;
    FString GetLastStateTreeControlOperation() const;

private:
    UPROPERTY(VisibleAnywhere)
    TObjectPtr<USceneComponent> SceneRoot;

    UPROPERTY(VisibleAnywhere)
    TObjectPtr<USphereComponent> CollisionComponent;

    // Chase camera so the web can switch the UE5 viewport to this AGV's viewpoint.
    UPROPERTY(VisibleAnywhere)
    TObjectPtr<USpringArmComponent> CameraBoom;

    UPROPERTY(VisibleAnywhere)
    TObjectPtr<UCameraComponent> ViewpointCamera;

    // F2 — live, camera-facing status label floated above this AGV.
    UPROPERTY(VisibleAnywhere)
    TObjectPtr<UWidgetComponent> NameplateWidgetComponent;

    UPROPERTY(VisibleAnywhere, Category="VCORE|AGV|Movement")
    TObjectPtr<UAGVMovementComponent> MovementComponent;

    UPROPERTY(VisibleAnywhere, Category="VCORE|AGV|Task")
    TObjectPtr<UAGVTaskComponent> TaskComponent;

    UPROPERTY(VisibleAnywhere, Category="VCORE|AGV|Task")
    TObjectPtr<UAGVTaskRunnerComponent> TaskRunnerComponent;

    UPROPERTY(EditAnywhere, Category="VCORE|AGV|Nameplate")
    FString AGVDisplayName = TEXT("AGV");

    UPROPERTY(EditAnywhere, Category="VCORE|AGV|Nameplate")
    bool bFaceNameplateToCameraInWorldSpace = true;

    UFUNCTION()
    void OnOverlapBegin(
        UPrimitiveComponent* OverlappedComponent,
        AActor* OtherActor,
        UPrimitiveComponent* OtherComp,
        int32 OtherBodyIndex,
        bool bFromSweep,
        const FHitResult& SweepResult);

    void UpdateMovement(float DeltaSeconds);
    // Distance-based safety net for autonomous Pickup/Dropoff arrival (complements the station's
    // physics-overlap trigger so the cell completes tasks even if the overlap doesn't fire).
    void CheckAutonomousStationArrival();
    void UpdateActionState(float DeltaSeconds);
    void TransitionTo(EAGVState NewState);
    void HandleCheckpointTransitions();
    float FindDistanceClosestToWorldLocation(const FVector& WorldLocation) const;
    void InitializeNameplateWidget();
    void UpdateNameplateWidget();
    void FaceNameplateToCamera();
    bool IsActiveState(EAGVState State) const;
    USplineComponent* GetPathSpline() const;
    float GetPathLength() const;

    TObjectPtr<AAGVSimController> Controller = nullptr;

    FString AgvId = TEXT("AGV-1");
    // Editor-placed transform captured at BeginPlay; the home pose offline AGVs return to.
    FTransform AuthoredTransform;
    EAGVState State = EAGVState::Idle;

    UPROPERTY(Transient)
    TObjectPtr<UTransportOrder> CurrentOrder = nullptr;

    UPROPERTY(Transient)
    TObjectPtr<AStationActor> TargetStation = nullptr;

    int32 CurrentStationId = 0;
    int32 TargetStationId = 0;

    float InitialDistance = 0.0f;

    bool bRunActive = false;
    bool bCarryingLoad = false;
    bool bHasTaskAssigned = false;

    int32 CompletedTasks = 0;
    double ActiveTimeSeconds = 0.0;
    double CurrentTaskStartedAt = 0.0;
};
