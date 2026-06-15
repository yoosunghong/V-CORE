#include "AGVTelemetryComponent.h"

#include "Common/UdpSocketBuilder.h"
#include "Dom/JsonObject.h"
#include "Interfaces/IPv4/IPv4Address.h"
#include "IWebSocket.h"
#include "IPAddress.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "SocketSubsystem.h"
#include "Sockets.h"

void UAGVTelemetryComponent::Configure(const FAGVTelemetrySettings& InSettings)
{
    Settings = InSettings;
}

void UAGVTelemetryComponent::SetupSocket()
{
    TeardownSocket();

    if (!ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM))
    {
        return;
    }

    if (Settings.UsesUdp())
    {
        UdpAddr = ResolveTelemetryAddress(Settings.UdpPort);
        if (UdpAddr.IsValid())
        {
            UdpSocket = FUdpSocketBuilder(TEXT("AGVTelemetrySocket"))
                .AsReusable()
                .WithBroadcast()
                .Build();

            if (!UdpSocket)
            {
                UE_LOG(LogTemp, Warning, TEXT("AGVTelemetry: failed to create UDP socket"));
            }
        }
    }

    if (Settings.UsesTcp())
    {
        TcpAddr = ResolveTelemetryAddress(Settings.TcpPort);
    }

    UE_LOG(LogTemp, Log, TEXT("AGVTelemetry: transport=%s host=%s udp=%d tcp=%d"),
        *Settings.Transport, *Settings.Host, Settings.UdpPort, Settings.TcpPort);
}

void UAGVTelemetryComponent::TeardownSocket()
{
    CloseTcpSocket();
    if (UdpSocket)
    {
        UdpSocket->Close();
        if (ISocketSubsystem* SocketSubsystem = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM))
        {
            SocketSubsystem->DestroySocket(UdpSocket);
        }
        UdpSocket = nullptr;
    }
    UdpAddr.Reset();
    TcpAddr.Reset();
}

void UAGVTelemetryComponent::SendPayload(
    const TSharedRef<FJsonObject>& Json,
    const TSharedPtr<IWebSocket>& WebSocket)
{
    FString Body;
    TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Body);
    FJsonSerializer::Serialize(Json, Writer);

    if (Settings.UsesUdp())
    {
        SendUdpPayload(Body);
    }
    if (Settings.UsesTcp())
    {
        SendTcpPayload(Body);
    }
    if (Settings.UsesWebSocket())
    {
        SendWebSocketPayload(Body, WebSocket);
    }
}

void UAGVTelemetryComponent::SendUdpPayload(const FString& Body)
{
    if (!UdpSocket || !UdpAddr.IsValid())
    {
        return;
    }

    FTCHARToUTF8 Converted(*Body);
    int32 BytesSent = 0;
    UdpSocket->SendTo(
        reinterpret_cast<const uint8*>(Converted.Get()),
        Converted.Length(),
        BytesSent,
        *UdpAddr);
}

void UAGVTelemetryComponent::SendTcpPayload(const FString& Body)
{
    if (!EnsureTcpConnected())
    {
        return;
    }

    const FString Line = Body + TEXT("\n");
    FTCHARToUTF8 Converted(*Line);
    const uint8* Data = reinterpret_cast<const uint8*>(Converted.Get());
    int32 Remaining = Converted.Length();

    while (Remaining > 0)
    {
        int32 BytesSent = 0;
        if (!TcpSocket->Send(Data, Remaining, BytesSent) || BytesSent <= 0)
        {
            UE_LOG(LogTemp, Warning, TEXT("AGVTelemetry: TCP send failed; reconnecting on next payload"));
            CloseTcpSocket();
            return;
        }

        Data += BytesSent;
        Remaining -= BytesSent;
    }
}

void UAGVTelemetryComponent::SendWebSocketPayload(
    const FString& Body,
    const TSharedPtr<IWebSocket>& WebSocket)
{
    if (WebSocket.IsValid() && WebSocket->IsConnected())
    {
        WebSocket->Send(Body);
    }
}

bool UAGVTelemetryComponent::EnsureTcpConnected()
{
    if (!TcpAddr.IsValid())
    {
        return false;
    }

    if (TcpSocket && TcpSocket->GetConnectionState() == SCS_Connected)
    {
        return true;
    }

    CloseTcpSocket();

    ISocketSubsystem* SocketSubsystem = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM);
    if (!SocketSubsystem)
    {
        return false;
    }

    TcpSocket = SocketSubsystem->CreateSocket(NAME_Stream, TEXT("AGVTelemetryTcpSocket"), false);
    if (!TcpSocket)
    {
        UE_LOG(LogTemp, Warning, TEXT("AGVTelemetry: failed to create TCP socket"));
        return false;
    }

    TcpSocket->SetNoDelay(true);
    if (!TcpSocket->Connect(*TcpAddr))
    {
        UE_LOG(LogTemp, Warning, TEXT("AGVTelemetry: failed to connect TCP socket to %s:%d"), *Settings.Host, Settings.TcpPort);
        CloseTcpSocket();
        return false;
    }

    UE_LOG(LogTemp, Log, TEXT("AGVTelemetry: TCP connected to %s:%d"), *Settings.Host, Settings.TcpPort);
    return true;
}

void UAGVTelemetryComponent::CloseTcpSocket()
{
    if (TcpSocket)
    {
        TcpSocket->Close();
        if (ISocketSubsystem* SocketSubsystem = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM))
        {
            SocketSubsystem->DestroySocket(TcpSocket);
        }
        TcpSocket = nullptr;
    }
}

TSharedPtr<FInternetAddr> UAGVTelemetryComponent::ResolveTelemetryAddress(int32 Port) const
{
    ISocketSubsystem* SocketSubsystem = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM);
    if (!SocketSubsystem)
    {
        return nullptr;
    }

    FIPv4Address ResolvedAddress;
    if (!FIPv4Address::Parse(Settings.Host, ResolvedAddress))
    {
        FAddressInfoResult Info = SocketSubsystem->GetAddressInfo(*Settings.Host, nullptr, EAddressInfoFlags::Default, NAME_None);
        if (Info.ReturnCode == SE_NO_ERROR && Info.Results.Num() > 0)
        {
            TSharedPtr<FInternetAddr> Address = Info.Results[0].Address->Clone();
            Address->SetPort(Port);
            return Address;
        }

        UE_LOG(LogTemp, Warning, TEXT("AGVTelemetry: could not resolve telemetry host %s"), *Settings.Host);
        return nullptr;
    }

    TSharedPtr<FInternetAddr> Address = SocketSubsystem->CreateInternetAddr();
    Address->SetIp(ResolvedAddress.Value);
    Address->SetPort(Port);
    return Address;
}
