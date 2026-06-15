#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "GameplayTagContainer.h"
#include "UObject/SoftObjectPtr.h"
#include "AGVTaskComponent.generated.h"

class UStateTree;
class UStateTreeComponent;
class UTransportOrder;

UENUM(BlueprintType)
enum class EAGVTaskLifecycleState : uint8
{
    Offline,
    Idle,
    Assigned,
    MovingToPickup,
    Loading,
    MovingToDropoff,
    Unloading,
    MovingToStation,
    WaitingForRoute,
    Completed,
    Failed,
    CollisionStopped
};

DECLARE_DYNAMIC_MULTICAST_DELEGATE_ThreeParams(
    FAGVTaskLifecycleChanged,
    EAGVTaskLifecycleState, PreviousState,
    EAGVTaskLifecycleState, NewState,
    const FString&, Reason);

/**
 * StateTree-ready lifecycle facade for an AGV.
 *
 * The current AGV still performs spline movement locally, but task/order state now has
 * a dedicated owner that can be backed by a StateTree asset in a later phase.
 */
UCLASS(ClassGroup=(VCORE), BlueprintType, meta=(BlueprintSpawnableComponent))
class VCORE_API UAGVTaskComponent : public UActorComponent
{
    GENERATED_BODY()

public:
    UAGVTaskComponent();

    UPROPERTY(BlueprintAssignable, Category="VCORE|AGV|Task")
    FAGVTaskLifecycleChanged OnLifecycleChanged;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="VCORE|AGV|Task")
    TSoftObjectPtr<UStateTree> LifecycleStateTree;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="VCORE|AGV|Task|StateTree")
    bool bRequireStateTreeForControl = true;

    void BindStateTreeComponent(UStateTreeComponent* InStateTreeComponent);

    UFUNCTION(BlueprintCallable, Category="VCORE|AGV|Task")
    bool ResetForRun(const FString& InAgvId, double TimestampSeconds);

    UFUNCTION(BlueprintCallable, Category="VCORE|AGV|Task")
    bool StopRun(double TimestampSeconds);

    UFUNCTION(BlueprintCallable, Category="VCORE|AGV|Task")
    bool AssignOrder(UTransportOrder* Order, int32 InTargetStationId, double TimestampSeconds);

    UFUNCTION(BlueprintCallable, Category="VCORE|AGV|Task")
    bool TransitionTo(EAGVTaskLifecycleState NewState, double TimestampSeconds, const FString& Reason);

    UFUNCTION(BlueprintCallable, Category="VCORE|AGV|Task")
    bool CompleteCurrentTask(double TimestampSeconds);

    UFUNCTION(BlueprintCallable, Category="VCORE|AGV|Task")
    bool FailCurrentTask(const FString& FailureReason, double TimestampSeconds);

    UFUNCTION(BlueprintPure, Category="VCORE|AGV|Task|StateTree")
    bool IsStateTreeControlReady() const;

    UFUNCTION(BlueprintPure, Category="VCORE|AGV|Task|StateTree")
    FString GetLastControlOperation() const { return LastControlOperation; }

    UFUNCTION(BlueprintPure, Category="VCORE|AGV|Task")
    EAGVTaskLifecycleState GetLifecycleState() const { return LifecycleState; }

    UFUNCTION(BlueprintPure, Category="VCORE|AGV|Task")
    FString GetLifecycleStateName() const;

    UFUNCTION(BlueprintPure, Category="VCORE|AGV|Task")
    FString GetFailureReason() const { return FailureReason; }

    UFUNCTION(BlueprintPure, Category="VCORE|AGV|Task")
    UTransportOrder* GetCurrentOrder() const { return CurrentOrder; }

    UFUNCTION(BlueprintPure, Category="VCORE|AGV|Task")
    int32 GetTargetStationId() const { return TargetStationId; }

    UFUNCTION(BlueprintPure, Category="VCORE|AGV|Task")
    double GetLastTransitionTimestampSeconds() const { return LastTransitionTimestampSeconds; }

    static FString LifecycleStateToString(EAGVTaskLifecycleState State);

private:
    bool StartStateTreeControl();
    void StopStateTreeControl(const FString& Reason);
    bool DispatchControlEvent(const FGameplayTag& EventTag, const FString& OperationName, double TimestampSeconds);
    bool DispatchLifecycleEvent(EAGVTaskLifecycleState NewState, double TimestampSeconds, const FString& Reason);
    bool CanExecuteControlOperation(const FString& OperationName) const;
    static FGameplayTag GetLifecycleEventTag(EAGVTaskLifecycleState State);

    UPROPERTY(Transient)
    TObjectPtr<UStateTreeComponent> StateTreeComponent = nullptr;

    UPROPERTY(Transient)
    TObjectPtr<UTransportOrder> CurrentOrder = nullptr;

    UPROPERTY(VisibleAnywhere, Category="VCORE|AGV|Task")
    EAGVTaskLifecycleState LifecycleState = EAGVTaskLifecycleState::Offline;

    UPROPERTY(VisibleAnywhere, Category="VCORE|AGV|Task")
    FString AgvId;

    UPROPERTY(VisibleAnywhere, Category="VCORE|AGV|Task")
    int32 TargetStationId = 0;

    UPROPERTY(VisibleAnywhere, Category="VCORE|AGV|Task")
    FString FailureReason;

    UPROPERTY(VisibleAnywhere, Category="VCORE|AGV|Task")
    double LastTransitionTimestampSeconds = 0.0;

    UPROPERTY(VisibleAnywhere, Category="VCORE|AGV|Task|StateTree")
    FString LastControlOperation;
};
