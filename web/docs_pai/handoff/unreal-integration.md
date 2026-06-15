# Unreal Engine 5.7 Integration Handoff

## Scope

Unreal owns the digital-twin visualization and hosts the chat experience through
a WebView. The chat UI itself is implemented by the `chat-web` frontend service.
The demo backend owns chat orchestration, tool validation, robot command
publication, and report generation. Unreal does not call the LLM, control
server, or database directly.

## Base URLs

- Chatbot backend: `http://localhost:8000`
- Chat WebView frontend: `http://localhost:5180`
- IoT platform demo: `http://localhost:8020`

Docker Compose service names are `chatbot-backend`, `chat-web`, and
`iot-platform-demo` when calling from another container on the `pai-demo`
network.

## WebView Chat UI

Load this URL inside the Unreal WebView:

```text
http://localhost:5180
```

The page handles:

- Creating a chat session.
- Sending user messages to `POST /chat/messages`.
- Subscribing to `WS /chat/sessions/{session_id}/events`.
- Rendering progress events and final report messages.

Recommended WebView settings:

- Enable keyboard focus for the input field.
- Allow WebSocket connections to `ws://localhost:8000`.
- Use a minimum surface size of 390 x 560 for embedded layouts.
- Use `http://localhost:5180` or `http://127.0.0.1:5180` as the page origin.

The backend CORS allowlist includes the default WebView origins on ports `5173`
and `5180`.

## Chat Session

The `chat-web` frontend creates a session when the chat UI opens. Use this
contract only if Unreal needs to drive the API directly for diagnostics.

```http
POST /chat/sessions
Content-Type: application/json
```

```json
{
  "user_id": "demo-user",
  "unreal_client_id": "ue-client-01"
}
```

Store the returned `session_id` and reuse it for subsequent chat messages and
the session event WebSocket.

## Chat Message

```http
POST /chat/messages
Content-Type: application/json
x-correlation-id: corr_demo_0001
```

```json
{
  "session_id": "session_replace_me",
  "message": "2번 bed의 식물을 수확해줘",
  "user_id": "demo-user",
  "unreal_client_id": "ue-client-01",
  "idempotency_key": "ue-chat-0001"
}
```

Expected response includes:

- `correlation_id`: trace id for logs and downstream events.
- `message.content`: Korean assistant acknowledgement or failure guidance.
- `command_id`: robot command id when a command was issued.
- `status`: command state such as `accepted` or `pending_confirmation`.
- `events`: synchronous progress events generated during request handling.

## Chat Progress WebSocket

```text
WS /chat/sessions/{session_id}/events
```

Use this stream for chatbot progress and final user-facing report events. Event
payloads follow the common `DomainEvent` shape:

```json
{
  "event_id": "evt_...",
  "event_type": "robot.command.completed",
  "correlation_id": "corr_demo_0001",
  "session_id": "session_replace_me",
  "command_id": "cmd_replace_me",
  "occurred_at": "2026-05-12T10:00:00Z",
  "payload": {}
}
```

## Digital-Twin Events

Unreal can poll or subscribe to IoT state events:

- `GET /digital-twin/events`
- `WS /digital-twin/events`

Robot movement sequence for harvest:

1. `robot.command.accepted`
2. `robot.moving`
3. `robot.harvesting`
4. `robot.command.completed`

Failure simulation emits `robot.command.failed`.

## Rendering Guidance

- `robot.moving`: move `payload.robot_id` toward `payload.target_bed_id`.
- `robot.harvesting`: play harvest animation at `payload.bed_id`.
- `robot.inspecting`: play inspection animation at `payload.bed_id`.
- `robot.command.completed`: mark the task complete and allow chat report display.
- `robot.command.failed`: stop movement and show a non-blocking failure status.

## Required Headers

Always forward `x-correlation-id` when Unreal creates one. If omitted, the
chatbot backend creates one and returns it in the response.
