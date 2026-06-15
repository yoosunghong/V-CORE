#pragma once

#include "CoreMinimal.h"
#include "AGVSimTypes.generated.h"

UENUM()
enum class EAGVTelemetryTransport : uint8
{
    Tcp,
    Udp,
    Both,
    WebSocket
};

USTRUCT()
struct FSimStartParams
{
    GENERATED_BODY()

    FString RunId;
    float Speed = 60.0f;
    int32 Duration = 3600;
    FString PolicyId = TEXT("POLICY_FIFO");
    int32 AgvCount = 3;
    float BottleneckThresholdSec = 10.0f;
};

/** Compact snapshot of sim meta + event ticker, streamed on process telemetry. */
USTRUCT()
struct FVcoreHudSnapshot
{
    GENERATED_BODY()

    bool bRunning = false;
    bool bPaused = false;
    float Speed = 1.0f;
    float ProgressPercent = 0.0f;
    int32 TasksCompleted = 0;
    int32 Collisions = 0;
    FString PolicyId;
    TArray<FString> RecentEvents;

    FString VerdictSummary;
    bool bVerdictPassed = true;
};

USTRUCT()
struct FAGVTelemetrySettings
{
    GENERATED_BODY()

    FString Host = TEXT("127.0.0.1");
    FString Transport = TEXT("tcp");
    int32 UdpPort = 9999;
    int32 TcpPort = 9998;
    FString CellId = TEXT("cell_demo");

    EAGVTelemetryTransport GetTransportMode() const
    {
        if (Transport.Equals(TEXT("udp"), ESearchCase::IgnoreCase))
        {
            return EAGVTelemetryTransport::Udp;
        }
        if (Transport.Equals(TEXT("both"), ESearchCase::IgnoreCase))
        {
            return EAGVTelemetryTransport::Both;
        }
        if (Transport.Equals(TEXT("ws"), ESearchCase::IgnoreCase))
        {
            return EAGVTelemetryTransport::WebSocket;
        }
        return EAGVTelemetryTransport::Tcp;
    }

    bool UsesUdp() const
    {
        const EAGVTelemetryTransport Mode = GetTransportMode();
        return Mode == EAGVTelemetryTransport::Udp || Mode == EAGVTelemetryTransport::Both;
    }

    bool UsesTcp() const
    {
        const EAGVTelemetryTransport Mode = GetTransportMode();
        return Mode == EAGVTelemetryTransport::Tcp || Mode == EAGVTelemetryTransport::Both;
    }

    bool UsesWebSocket() const
    {
        return GetTransportMode() == EAGVTelemetryTransport::WebSocket;
    }
};
