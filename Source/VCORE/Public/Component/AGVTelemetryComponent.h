#pragma once

#include "CoreMinimal.h"
#include "AGVSimTypes.h"
#include "Components/ActorComponent.h"
#include "Templates/SharedPointer.h"
#include "AGVTelemetryComponent.generated.h"

class FInternetAddr;
class FJsonObject;
class FSocket;
class IWebSocket;

UCLASS(ClassGroup=(VCORE), meta=(BlueprintSpawnableComponent))
class VCORE_API UAGVTelemetryComponent : public UActorComponent
{
    GENERATED_BODY()

public:
    void Configure(const FAGVTelemetrySettings& InSettings);
    const FAGVTelemetrySettings& GetSettings() const { return Settings; }
    const FString& GetCellId() const { return Settings.CellId; }

    void SetupSocket();
    void TeardownSocket();
    void SendPayload(const TSharedRef<FJsonObject>& Json, const TSharedPtr<IWebSocket>& WebSocket);

private:
    void SendUdpPayload(const FString& Body);
    void SendTcpPayload(const FString& Body);
    void SendWebSocketPayload(const FString& Body, const TSharedPtr<IWebSocket>& WebSocket);
    bool EnsureTcpConnected();
    void CloseTcpSocket();
    TSharedPtr<FInternetAddr> ResolveTelemetryAddress(int32 Port) const;

    UPROPERTY(EditAnywhere, Category="VCORE|Telemetry")
    FAGVTelemetrySettings Settings;

    FSocket* UdpSocket = nullptr;
    FSocket* TcpSocket = nullptr;
    TSharedPtr<FInternetAddr> UdpAddr;
    TSharedPtr<FInternetAddr> TcpAddr;
};
