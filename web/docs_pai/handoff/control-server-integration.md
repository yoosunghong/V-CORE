# Control Server Handoff

## Responsibility

The control server provides smart-farm state and accepts control-domain tasks.
In this demo it is an in-memory FastAPI service with stable API boundaries for a
future production adapter.

## Key APIs

- `GET /farm/status`: greenhouse, bed, and sensor snapshot summary.
- `GET /beds/{bed_id}`: bed crop, growth stage, harvestability, and accessibility.
- `POST /tasks`: idempotent task acceptance.
- `GET /tasks/{task_id}`: task status lookup.
- `PATCH /tasks/{task_id}`: demo task status update.
- `POST /events`: control event publication.
- `GET /events`: verification event list.

## Chatbot Dependency

The chatbot backend uses the `ControlServerClient` port. Local unit tests use
`DemoControlServerClient`; Docker Compose uses `HttpControlServerClient` through:

```env
CONTROL_SERVER_CLIENT_MODE=http
CONTROL_SERVER_BASE_URL=http://control-server-demo:8010
```

## Idempotency

`POST /tasks` requires `idempotency_key`. Repeated requests with the same key
return the original task instead of creating a duplicate.
