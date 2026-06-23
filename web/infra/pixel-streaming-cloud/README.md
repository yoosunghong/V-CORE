# V-CORE cloud Pixel Streaming edge

This stack hosts the UE Pixel Streaming signaling/player service and a TURN
relay on a public Linux VM. UE5 remains on the GPU workstation and publishes to
the cloud over an outbound secure WebSocket. Browsers receive interactive video
over WebRTC; TURN relays media when a direct ICE path is unavailable.

## Required cloud VM

- Linux x86_64, Docker Engine with Compose v2, a static public IPv4 address.
- 2 vCPU / 4 GB RAM is enough for signaling and a small TURN demo. TURN network
  egress, not CPU, is the main sizing/cost factor.
- Firewall ingress: TCP `80`, TCP/UDP `443`, TCP/UDP `3478`, and UDP
  `49160-49200`. Do not expose signaling's internal ports `80` or `8888`
  directly from Docker.

## Cloudflare DNS

Create three `A` records pointing to the VM's static IPv4 address:

| Name | Proxy status |
|---|---|
| `stream.v-core.yoosung.dev` | DNS only |
| `streamer.v-core.yoosung.dev` | DNS only |
| `turn.v-core.yoosung.dev` | DNS only |

DNS-only is intentional. Cloudflare's normal proxy/Tunnel can front the HTTPS
application, but it is not the UDP TURN/WebRTC data plane. Caddy obtains public
TLS certificates after DNS and ports 80/443 are reachable.

## Start the edge

Copy this repository (including the version-matched
`PixelStreaming2WebServers` directory) to the VM, then:

> Current workspace check: `VCORE.uproject` targets UE 5.7 while the checked-out
> infrastructure reports `DOWNLOAD_VERSION=UE5.6`. It is suitable for testing
> the existing integration, but replace it with the UE 5.7-matched
> Pixel Streaming Infrastructure release before treating the service as
> production-supported.

```bash
cd web/infra/pixel-streaming-cloud
cp .env.example .env
# edit .env: PUBLIC_IP, ACME_EMAIL, TURN_USER, TURN_PASSWORD
docker compose config
docker compose up -d --build
docker compose logs -f edge signalling turn
```

Verify `https://stream.v-core.yoosung.dev` loads before launching UE5.

## Connect the UE5 workstation

On Windows, set the publisher URL and use the cloud launcher:

```powershell
$env:VCORE_PIXEL_STREAMING_URL = "wss://streamer.v-core.yoosung.dev"
.\LaunchPixelStreaming2Cloud.bat
```

The publisher connection is outbound, so the workstation normally needs no
inbound port-forward. Its firewall must allow outbound TCP 443 and outbound UDP
3478 / 49160-49200. If UDP is blocked, TURN can use TCP 3478, with higher
latency.

## Point the operator UI at the cloud player

Set this in `web/.env`, then rebuild/restart the backend:

```dotenv
UE5_VIEW_URL=https://stream.v-core.yoosung.dev
```

```bash
cd web
docker compose up -d --build chatbot-backend chat-web
```

The existing `v-core.yoosung.dev` Cloudflare Tunnel may continue serving the
operator UI. The iframe loads the player from the cloud domain, and keyboard,
mouse, touch, and data-channel input return to UE5 over the same WebRTC session.

## Production hardening

- Protect the operator UI with Cloudflare Access or application auth. Do not
  rely on an unguessable URL.
- Rotate the static TURN credential regularly. For a multi-user production
  service, replace it with time-limited TURN REST credentials.
- Add VM/network monitoring and TURN egress alerts. One 1080p stream can consume
  several Mbps continuously.
- Keep the Pixel Streaming Infrastructure branch/version aligned with the UE5
  Pixel Streaming plugin used to package the application.
