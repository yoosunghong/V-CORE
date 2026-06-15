# CI Candidate Commands

Section 2 defines bootstrap-level checks only. Service-specific test commands will be added as sections 3, 5, 7, and 9 are implemented.

## Required Bootstrap Checks

```sh
docker compose config
```

Validates Docker Compose syntax, environment interpolation, service names, networks, volumes, and healthcheck declarations.

```sh
./scripts/run-e2e.sh
```

Runs the current smoke-test entry point. At this stage it validates Compose configuration and reserves the E2E hook for the harvest-bed scenario.

```sh
sh -n scripts/dev-up.sh
sh -n scripts/dev-down.sh
sh -n scripts/seed-demo-data.sh
sh -n scripts/run-e2e.sh
sh -n scripts/verify-ollama-model.sh
```

Validates shell script syntax without starting local services.

## Future Service Checks

```sh
docker compose build
docker compose up -d
docker compose ps
docker compose logs --no-color --tail=100 chatbot-backend
docker compose exec chatbot-backend pytest
docker compose exec control-server-demo pytest
docker compose exec iot-platform-demo pytest
LLM_PROVIDER=ollama OLLAMA_BASE_URL=http://127.0.0.1:11434 scripts/verify-ollama-model.sh
```
