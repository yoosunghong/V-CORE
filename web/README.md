# Virtual Process Chatbot (web)

Virtual Process digital-twin chatbot workspace for the VCORE UE5 AGV cell.
Derived from the pai_chatbot LangGraph multi-agent demo. See
[../docs/spec_virtual_process.md](../docs/spec_virtual_process.md).

## Quick Start

1. Copy environment defaults.

```sh
cp .env.example .env
```

2. Start the Docker development stack.

```sh
docker compose up --build
```

The stack starts `ngrok` automatically. Once it is healthy, open the local ngrok
dashboard at <http://localhost:4040> or run `docker compose logs ngrok` to see
the public forwarding URL.

The legacy `iot-platform-demo` mock is not part of the default stack. Start it only
when needed with `docker compose --profile legacy up iot-platform-demo`.

3. Stop the stack.

```sh
docker compose down
```

To turn only ngrok off or on while leaving the rest of the stack running:

```sh
docker compose stop ngrok
docker compose up -d ngrok
```

## CI Candidate Commands

The current repository bootstrap can be checked with:

```sh
docker compose config
./scripts/run-e2e.sh
```

Detailed candidate commands are tracked in `docs/ci/candidate-commands.md`.
