# TECKSTACK.md

This document summarizes the project technology stack and the reasons for the selected technologies.

## Core Technology Stack

| Area | Recommended Technology | Purpose |
| --- | --- | --- |
| Containerization | Docker, Docker Compose | Standard demo environment execution |
| Chatbot Backend | Python 3.12, FastAPI | API, WebSocket, LLM orchestration |
| Agent Workflow | LangGraph | Multi-response agent state machine and node routing |
| Agent Checkpointing | LangGraph checkpointer | Per-request graph state checkpoint extension point |
| Dependency Management | uv or Poetry | Reproducible Python environments |
| LLM Runtime | Ollama | GPU farm LLM execution |
| LLM Model | Gemma 4 E2B Quantized Model | Local/on-premise demo LLM |
| Relational DB | PostgreSQL | Sessions, commands, task states, domain data |
| Vector DB | Qdrant | RAG embedding search |
| Timeseries DB | TimescaleDB or InfluxDB | Sensor data and robot state history |
| Messaging | Redis Streams or NATS | Asynchronous command/event delivery |
| Demo Control Server | FastAPI | Control API mock and task management |
| Demo IoT Platform | FastAPI | Robot/sensor/actuator mock |
| API Documentation | OpenAPI, AsyncAPI | Handoff contract documentation |
| Testing | pytest, httpx, pytest-asyncio | Unit and integration testing |
| Logging | structlog or JSON logging formatter | Structured traceable logs |
| Frontend Integration | HTTP, WebSocket | Unreal chat UI and event integration |
| Digital Twin | Unreal Engine 5.7 | Smart farm and robot visualization |

## Backend Language and Framework

Python and FastAPI are the primary recommendations because they work well with LLM orchestration, RAG, and agent ecosystems while providing convenient OpenAPI generation and async support.

## LLM Orchestration

The demo uses LangGraph for the multi-response chat agent workflow while keeping
domain-specific agents and external systems behind explicit interfaces.

- `ChatOrchestrator`
- `LangGraphMultiResponseAgent`
- `FarmStatusAgent`
- `RobotControlAgent`
- `ToolRouter`
- `ReportAgent`
- `AgentFailurePolicy`

The LLM runtime is abstracted behind the `LlmGateway` interface.

The current backend uses LangGraph's in-process checkpointer for graph execution
state and repository-backed persistence for business state. Production
deployment should replace the in-process graph checkpointer and event bus with
durable implementations before running multiple backend workers.

## Data Storage

### PostgreSQL

Stores:

- User sessions
- Chat messages
- LLM request/response metadata
- Robot commands
- Task states
- Smart farm domain data

### Qdrant

Stores:

- Operation manuals
- Crop management guides
- Robot task instructions
- Facility failure response documents
- Handoff documents

### TimescaleDB or InfluxDB

Stores:

- Temperature, humidity, CO2, and illumination data
- Bed growth state timeseries
- Robot location and task state history
- Actuator state history

## Communication Methods

| Segment | Recommended Method | Description |
| --- | --- | --- |
| Unreal -> Chatbot Backend | HTTP POST or WebSocket | Chat requests |
| Chatbot Backend -> Unreal | WebSocket | Progress and completion messages |
| Chatbot Backend -> Ollama | HTTP | LLM inference |
| Chatbot Backend -> Control Server | HTTP | Task and status queries |
| Chatbot Backend -> IoT Platform | HTTP or Messaging | Robot command publishing |
| IoT Platform -> Chatbot Backend | Webhook or Messaging | Completion/failure events |
| IoT Platform -> Unreal | WebSocket or polling | Digital twin state updates |

## WebView Chat Frontend

The Unreal Engine 5.7 chat UI is provided through a WebView-rendered web frontend instead of native widgets.

Recommended stack:

- TypeScript, React, Vite
- WebSocket API for session progress events
- Fetch API for session creation and message transmission
- Docker Compose service: `chat-web`
