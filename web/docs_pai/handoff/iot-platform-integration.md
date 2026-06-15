# IoT Platform Handoff

## Responsibility

The IoT platform receives robot commands, emits robot progress events, provides
sensor/actuator mocks, and exposes events for Unreal digital-twin synchronization.

## Key APIs

- `POST /robots/commands`: receive a robot command.
- `GET /robots/commands/{command_id}`: command status lookup.
- `POST /robots/commands/{command_id}/simulate-failure`: demo failure event.
- `GET /robots`: robot snapshots.
- `GET /robots/{robot_id}`: one robot state.
- `GET /sensors/snapshot`: sensor values.
- `GET /actuators`: actuator states.
- `PATCH /actuators/{actuator_id}`: update demo actuator state.
- `GET /digital-twin/events`: polling event feed.
- `WS /digital-twin/events`: WebSocket event feed.

## Chatbot Dependency

The chatbot backend uses the `IotCommandClient` port. Local unit tests use
`DemoIotCommandClient`; Docker Compose uses `HttpIotCommandClient` through:

```env
IOT_PLATFORM_CLIENT_MODE=http
IOT_PLATFORM_BASE_URL=http://iot-platform-demo:8020
```

## Event Contract

Every event includes `event_type`, `correlation_id`, optional `session_id`,
optional `command_id`, `occurred_at`, and `payload`.

Completion events should be forwarded to the chatbot backend webhook:

```http
POST /events/robot-command
Content-Type: application/json
```

```json
{
  "event_type": "robot.command.completed",
  "correlation_id": "corr_demo_0001",
  "session_id": "session_replace_me",
  "command_id": "cmd_replace_me",
  "payload": {
    "robot_id": "robot_demo_1",
    "bed_id": 2
  }
}
```
