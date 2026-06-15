# Backend Handoff

## Services

- `services/chatbot-backend`: chat orchestration, tool routing, LLM gateway ports,
  control client, IoT client, session state, webhook handling.
- `services/control-server-demo`: smart-farm state and task API mock.
- `services/iot-platform-demo`: robot command, sensor, actuator, and event API mock.
- `services/data-seeder`: deterministic sample data and RAG payload builders.

## Extension Points

- Replace `DemoControlServerClient` with an HTTP or production adapter behind
  `ControlServerClient`.
- Replace `DemoIotCommandClient` with a broker or production HTTP adapter behind
  `IotCommandClient`.
- Replace `RuleBasedLlmGateway` with `OllamaLlmGateway` or another model gateway
  behind `LlmGateway`.
- Replace in-memory repositories with PostgreSQL repositories using the schema in
  `infra/postgres/init`.

## Verification Commands

```sh
cd services/chatbot-backend && ./.venv/bin/python -m pytest
cd services/control-server-demo && ../chatbot-backend/.venv/bin/python -m pytest
cd services/iot-platform-demo && ../chatbot-backend/.venv/bin/python -m pytest
PYTHONPYCACHEPREFIX=/private/tmp/pai_chatbot_pycache python3 -m compileall -q services/data-seeder/scripts
```

## Known Runtime Gaps

- Docker Compose full startup must be verified on a machine with Docker.
- Ollama model pull and inference must be verified only on the GPU farm or LLM
  validation machine.
- Unreal visual playback must be verified by the Unreal owner in Unreal Engine 5.7.
