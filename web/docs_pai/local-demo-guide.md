# Local Demo Guide

## Constraints

This guide runs the chatbot against real Ollama inference by default. The
deterministic `rule_based` gateway is kept only for unit tests or constrained CI.

## Environment

```sh
cp .env.example .env
```

Important defaults:

```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=gemma4:e2b
OLLAMA_IMAGE_TAG=0.20.0
NVIDIA_VISIBLE_DEVICES=all
NVIDIA_DRIVER_CAPABILITIES=compute,utility
CONTROL_SERVER_CLIENT_MODE=http
IOT_PLATFORM_CLIENT_MODE=http
```

## Start Services

```sh
./scripts/dev-up.sh
```

The core services are:

- Chatbot backend: `http://localhost:8000`
- Control server demo: `http://localhost:8010`
- IoT platform demo: `http://localhost:8020`
- Ollama: `http://localhost:11434`

## Smoke Test

```sh
./scripts/run-e2e.sh
```

The script validates Compose config and runs the Python tests that cover the
harvest scenario, failure handling, and service API contracts.

## Manual Harvest Flow

1. `POST http://localhost:8000/chat/messages` with
   `unreal/integration-samples/payloads/chat-message-harvest-bed.json`.
2. Read `command_id`, `session_id`, and `correlation_id` from the response.
3. Check robot events through `GET http://localhost:8020/digital-twin/events`.
4. Forward the completion event to `POST http://localhost:8000/events/robot-command`.

## LLM Runtime

Compose starts Ollama and runs an `ollama-model` init service that pulls
`OLLAMA_MODEL`. The chatbot waits for that init service before starting. If a
machine should not run an LLM, set `LLM_PROVIDER=rule_based` explicitly for that
run.
