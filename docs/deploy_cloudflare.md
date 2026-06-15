# Deploy: V-CORE web demo at `v-core.yoosung.dev`

The V-CORE web demo is served from the **local machine** through a Cloudflare Tunnel.
UE5, Ollama, and the backend all run locally; only the browser ↔ frontend hop crosses
the internet. The portfolio site (`yoosung.dev`) links to it from the temporary
**v-core** project page (Live Demo button in the info panel).

## Architecture

```
Browser ── HTTPS ──> v-core.yoosung.dev ── Cloudflare Tunnel ──> localhost:5173 (chat-web nginx)
                                                                       │ same-origin reverse proxy
                                                                       ▼
                                                                  backend :8000
                                                                       │ localhost
                                                          ┌────────────┼────────────┐
                                                       UE5 :7777   Ollama :11434   Postgres/Redis
```

- `chat-web` nginx (`web/services/chat-web/nginx.conf`) serves the static overlay **and**
  proxies `/api`, `/chat` (WebSocket), `/unreal` (SSE), `/dashboard`, `/events`, `/ps` to
  the backend on `:8000`. Everything is same-origin → **no CORS change, no `api.` subdomain,
  no frontend rebuild** (the same-origin default in `chat-web/src/api.ts` already applies).
- `/internal/ue5/*` is **not** proxied by nginx, so the public edge cannot reach the UE5
  event-ingest routes. UE5 reaches the backend over the local Docker network.

## One-time setup

1. **Run the stack locally** (chat-web nginx on `:5173`, backend on `:8000`, ollama, postgres):
   ```
   cd web
   docker compose up -d
   ```
   Start UE5 (AGVSimController binds `:7777`) and confirm Ollama is serving `qwen3.5:2b`.

2. **Install + authenticate cloudflared** (Windows):
   ```
   winget install --id Cloudflare.cloudflared
   cloudflared tunnel login          # pick the yoosung.dev zone
   ```

3. **Create the tunnel and wire DNS:**
   ```
   cloudflared tunnel create vcore
   cloudflared tunnel route dns vcore v-core.yoosung.dev   # creates the CNAME at Cloudflare
   ```

4. **Configure ingress:** copy `web/infra/cloudflared/config.example.yml` to
   `C:\Users\PC\.cloudflared\config.yml` and fill in the `<tunnel-id>` (printed by step 3,
   also the credentials JSON filename).

5. **Run the tunnel** (foreground to test, then install as a service):
   ```
   cloudflared tunnel run vcore
   cloudflared service install        # persists across reboots
   ```

6. **Publish the portfolio link:** the temporary `v-core` project is already wired in the
   portfolio repo (`portfolio/src/data/projects/project5.js` + Live Demo card in
   `ProjectDetail.jsx`). Commit and push `main` in `C:\Users\PC\Documents\yoosung-h`; the
   `Deploy Vite portfolio to Pages` GitHub Action rebuilds and deploys. The Live Demo button
   then points to `https://v-core.yoosung.dev`.

## Operating notes

- **Availability:** the demo is reachable only while the local machine, the stack, and
  `cloudflared` are running. The portfolio project page itself is always up (GitHub Pages);
  only the Live Demo link goes dark when the machine is off.
- **Optional gating:** add a **Cloudflare Access** policy on `v-core.yoosung.dev` (email OTP)
  if you don't want it publicly reachable between demos. Free for low seat counts.
- **Bring it down:** stop `cloudflared` (or the service); the hostname returns 502 until it
  resumes. No portfolio change needed.
