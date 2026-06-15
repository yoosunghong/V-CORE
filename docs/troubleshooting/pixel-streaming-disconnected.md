# Troubleshooting: UE5 viewport shows "DISCONNECTED. CLICK TO RESTART"

**Date:** 2026-06-09
**Area:** Web frontend (`chat-web`) ↔ UE5 Pixel Streaming
**Status:** Resolved

---

## Symptom

A simulation was started from the chat, and the AGV cell ran normally **inside the UE5
standalone window** — but the embedded viewport on the web frontend (`http://localhost:5199`)
showed the Pixel Streaming overlay:

```
DISCONNECTED. CLICK TO RESTART
```

No video ever appeared in the web app, even though UE5 was clearly rendering.

A related, secondary symptom: when a run finished, the in-viewport HUD froze on the last
live frame (e.g. `RUNNING · 25%`) instead of returning to idle.

---

## Environment

| Component | Where | Port |
|---|---|---|
| UE5 standalone (`AGVSimController` + Pixel Streaming streamer) | host | control `:7777`, streams to `:8888` |
| Pixel Streaming 2 signalling server ("Wilbur", Node) | host | player page `:8880`, streamer `:8888`, SFU `:8889` |
| `chat-web` (React, embeds the player page in an `<iframe>`) | Docker | `:5199` |
| `chatbot-backend` (FastAPI) | Docker | `:8000` |

Launched via `LaunchPixelStreaming2Standalone.bat`, which starts the signalling server and
then launches UE with `-PixelStreamingURL=ws://127.0.0.1:8888`. The frontend embeds
`UE5_VIEW_URL` (`http://localhost:8880`) as the viewport, appending `?AutoConnect=true`.

The "DISCONNECTED. CLICK TO RESTART" text is **not** in the React source — it is rendered by
the Pixel Streaming player UI inside the iframe.

---

## Investigation

The key was to confirm each hop of the pipeline rather than guess. The whole server side
turned out to be healthy; the failure was entirely browser-side.

### 1. Are the ports listening?

```powershell
Get-NetTCPConnection -State Listen -LocalPort 7777,8880,8888
```

All three listening. The player page returned HTTP 200:

```powershell
Invoke-WebRequest -UseBasicParsing "http://localhost:8880"   # HTTP 200
```

### 2. Is UE's streamer actually connected to the signalling server?

```powershell
Get-NetTCPConnection -State Established -LocalPort 8888
# -> an established connection from 127.0.0.1, owned (other end) by UnrealEditor.exe
```

So UE's Pixel Streaming **streamer is connected** to signalling on `:8888`.

### 3. Is the Pixel Streaming plugin enabled / config correct?

- `VCORE.uproject` → `PixelStreaming2` plugin `"Enabled": true`. ✓
- `web/.env` → `UE5_VIEW_URL=http://localhost:8880` (the **player page**, not the streamer
  WS port). ✓ — note `docs/spec_unreal.md` previously documented `:8888` here, which is wrong
  and would itself produce a DISCONNECTED iframe; that doc has been corrected.
- Pixel Streaming frontend **AFK timeout** defaults to **off**, so idle-disconnect was ruled out.

### 4. The decisive evidence — the signalling server log

`PixelStreaming2WebServers/SignallingWebServer/logs/server-<date>.log` showed a steady
stream of streamer `ping`/`pong` (`DefaultStreamer`), confirming UE was connected and
healthy — but **not a single player connection event** for the entire session.

> Conclusion: the streaming backend was fine. The **browser player never established (or
> never retried) its signalling WebSocket**, so the iframe sat on the terminal
> "DISCONNECTED. CLICK TO RESTART" overlay.

---

## Root cause

The embedded Pixel Streaming player gives up after a small, fixed number of reconnect
attempts (`MaxReconnectAttempts`, default **3**) and then shows the terminal
"DISCONNECTED. CLICK TO RESTART" overlay **without retrying again**.

In this setup the iframe mounts and tries to connect around the time UE/the streamer is
still coming up (UE takes ~20s to load the map and register its streamer). The player
exhausts its 3 attempts, gives up, and never reconnects even after UE's streamer is fully
registered — so the user is left staring at a dead overlay while UE happily streams to a
signalling server that has no player attached.

---

## Fix

Make the embedded player keep retrying until UE's streamer is available, instead of giving
up after 3 attempts. The Pixel Streaming frontend reads `MaxReconnectAttempts` from the URL,
so the iframe `src` now passes it alongside `AutoConnect`:

`web/services/chat-web/src/App.tsx` (viewport iframe):

```tsx
src={viewport.stream_url
  ? `${viewport.stream_url}${viewport.stream_url.includes('?') ? '&' : '?'}AutoConnect=true&MaxReconnectAttempts=999`
  : ""}
```

Because the frontend is built into the image (no volume mount), the change requires a
rebuild + recreate of `chat-web`, **and the browser tab must be hard-reloaded**
(Ctrl+Shift+R) to pick up the new bundle.

```powershell
docker compose -f web/docker-compose.yml build chat-web
docker compose -f web/docker-compose.yml up -d chat-web
```

### Documentation fix

`docs/spec_unreal.md` was corrected from `UE5_VIEW_URL=http://localhost:8888` to
`http://localhost:8880`, with a note that the value must point at the player page, not the
streamer WebSocket port.

---

## Verification

1. Hard-refresh `http://localhost:5199`, start a simulation.
2. The viewport connects on its own (no manual "click to restart").
3. `SignallingWebServer/logs/server-<date>.log` now shows a **player connection** followed by
   WebRTC negotiation (offer/answer/ICE), confirming the browser attached to the streamer.

---

## Related fix — frozen HUD on run end

UE5 emits **no terminal frame** when a run ends — it simply stops streaming telemetry. The
backend SSE (`/unreal/telemetry/stream`) treated frames older than 5s as stale and then went
silent for the `agvs`/`process`/`hud` events, so the web overlay kept the last live frame
forever (HUD stuck on `RUNNING · 25%`).

`web/services/chatbot-backend/app/interfaces/http.py` — the idle branch now pushes explicit
reset frames so the overlay returns to idle:

```python
yield _sse("agvs", [])
yield _sse("process", {"running": False, "paused": False})
yield _sse("hud", None)
# ...then the IoT mock telemetry for the metric cards
```

`updateDashboardFromProcess` in `App.tsx` was also hardened to leave the Uptime card
untouched when `uptime` is absent (the idle reset frame), instead of forcing it to 0%.

---

## Related fix — play button on a black screen (autoplay blocked)

**Date:** 2026-06-09

After the reconnect fix above, a later launch showed a different terminal state: the viewport
connected (no "DISCONNECTED"), but instead of rendering it showed a **play button on a black
screen**. The signalling log confirmed a healthy player connection + WebRTC negotiation — the
stream was arriving, it just wasn't playing.

**Root cause — browser autoplay policy.** The Pixel Streaming frontend's `AutoPlayVideo` flag
defaults to `true`, but UE launches with `-AudioMixer`, so the media track carries audio.
Browsers block autoplay of *audible* media until a user gesture, so the frontend falls back to
the play button. Muted video is exempt from that policy, but `StartVideoMuted` defaults to
`false` — so the stream stayed paused behind the button.

**Fix.** Force `StartVideoMuted=true` (and `AutoPlayVideo=true` explicitly) on the iframe URL.
The player flags are now a single declarative source of truth in `App.tsx` so a future edit
cannot drop one and silently reintroduce a manual-interaction overlay:

```ts
// web/services/chat-web/src/App.tsx
const pixelStreamingPlayerParams: Record<string, string> = {
  AutoConnect: "true",        // skip the connect overlay
  AutoPlayVideo: "true",      // play as soon as media arrives
  StartVideoMuted: "true",    // required: audible autoplay is blocked, muted is allowed
  MaxReconnectAttempts: "999" // keep retrying while UE/streamer boots
};
```

`withPixelStreamingParams()` applies every entry of this map to the iframe `src`. The viewport
is muted by design — the AGV cell has no meaningful audio.

---

## Quick checklist for next time

- [ ] Viewport shows a **play button**? → `StartVideoMuted=true` missing/dropped from the iframe params (audible-autoplay block).
- [ ] `:7777`, `:8880`, `:8888` listening? (`Get-NetTCPConnection -State Listen`)
- [ ] Player page returns 200? (`Invoke-WebRequest http://localhost:8880`)
- [ ] UE streamer connected? (`Get-NetTCPConnection -State Established -LocalPort 8888` → owned by UnrealEditor)
- [ ] Signalling log shows a **player** connection, not just streamer ping/pong?
- [ ] `UE5_VIEW_URL` points at the **player page** `:8880`, not the streamer `:8888`?
- [ ] Browser tab hard-reloaded after a `chat-web` rebuild?
