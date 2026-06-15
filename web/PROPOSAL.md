# PROPOSAL.md

## Project Overview

This project is a demonstration prototype of a chatbot system for a smart farm digital twin platform. Users request tasks through a chat UI in an Unreal Engine 5.7-based digital twin frontend, and the chatbot backend orchestrates control server, database, IoT platform, and robot control workflows using LLMs and tool calling.

Representative scenario:

> When a user enters “Harvest the plants in bed #2,” the chatbot backend analyzes the intent and target through the LLM, sends a robot control command to the IoT platform, and the Unreal digital twin visualizes the robot moving to bed #2 and performing the harvesting task. After completion, the completion event is propagated back, and the LLM generates a user-facing report message displayed in the chat UI.

## Goals

- Build a Docker-based demo environment
- Establish a production-scalable architecture for the chatbot backend
- Validate integration with GPU farm-based Ollama LLM instances
- Validate function calling, tool calling, and optionally multi-agent orchestration
- Define communication boundaries with the demo control server, demo DB, vector DB, timeseries DB, and demo IoT platform
- Provide integration interfaces for the Unreal Engine 5.7 digital twin frontend
- Provide maintainable documentation and API contracts suitable for project handoff

## Non-Goals

- Implementing the entire production smart farm feature set
- Building a robot control system with production-grade safety certification
- Optimizing for large-scale concurrent users
- Implementing a full operational control system
- Implementing the entire Unreal project internally

## Main Users

- Demo users: Request robot tasks through the Unreal frontend chatbot
- Chatbot backend engineers: Develop LLM, tool calling, and external integrations
- Control server engineers: Manage task status, smart farm status, and event integrations
- IoT platform engineers: Manage robot/sensor/actuator control interfaces
- Unreal engineers: Manage digital twin visualization and chat UI

## Core Demo Flow

1. The user enters a natural language command in the Unreal chat UI.
2. The Unreal frontend sends the chat request to the control server or chatbot gateway.
3. The chatbot backend sends context to the GPU farm hosting the LLM instance.
4. The LLM determines intent, target, and required tools.
5. A robot control agent or tool call publishes commands to the IoT platform.
6. The IoT platform publishes robot task status events.
7. The Unreal digital twin subscribes to or retrieves robot states and visualizes them.
8. Robot task completion events are delivered back to the chatbot backend.
9. The LLM generates a completion report message.
10. The completion message is displayed in the Unreal chat UI.

## Recommended Directory Structure

```text
pai_chatbot/
  AGENTS.md
  PLAN.md
  PROPOSAL.md
  TECKSTACK.md
  ARCHITECTURE.md
  DONE.md
```

## Demo Success Criteria

- Core demo services run with `docker compose up`
- Gemma 4 E2B quantized model calls work inside the Ollama container
- Commands entered in the Unreal chat UI reach the chatbot backend
- The LLM generates robot control tool calls
- The IoT platform mock changes robot state from in-progress to completed
- The Unreal digital twin receives events for robot motion and completion states
- A user-friendly Korean completion report message is displayed after completion

## Major Risks

- Function-calling stability of the Gemma 4 E2B quantized model
- Ollama tool-calling format support level
- Real-time communication method between Unreal and backend is not finalized
- API differences between the demo IoT platform and the real IoT platform
- Possibility of the LLM generating incorrect control commands
- Degraded context quality if the RAG scope is unclear
