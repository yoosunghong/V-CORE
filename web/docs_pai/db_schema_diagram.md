# Smart Farm Digital Twin Chatbot Database Specification

This document details the database architecture and schema specifications for the Smart Farm Digital Twin Chatbot system. The system leverages a hybrid database model utilizing **PostgreSQL** for relational metadata and chat management, **TimescaleDB** for high-write timeseries sensor logs, and **Qdrant** for semantic vector indexing.

---

## 1. System Database Architecture (ERD)

The following diagram illustrates the relationship between the core relational database tables, the timeseries storage layer, the vector store, and external mock boundaries.

```mermaid
classDiagram
    %% Styles Configuration
    classDef internal fill:#1a1b26,stroke:#7aa2f7,stroke-width:2px,color:#a9b1d6;
    classDef external fill:#1f2335,stroke:#f7768e,stroke-width:2px,stroke-dasharray: 5 5,color:#c0caf5;
    classDef tempMock fill:#16161e,stroke:#e0af68,stroke-width:1px,stroke-dasharray: 3 3,color:#9ece6a;

    %% ----------------------------------------------------
    %% PostgreSQL Core Chatbot Backend Tables (Internal)
    %% ----------------------------------------------------
    subgraph PostgreSQL ["PostgreSQL (Core Relational Database)"]
        class chat_sessions internal;
        class chat_messages internal;
        class robot_commands internal;
        class greenhouses internal;
        class beds internal;
        class robots internal;
        class actuators internal;
        class control_tasks internal;
        class domain_events internal;

        class greenhouses {
            +text greenhouse_id [PK]
            +text name
            +text location
            +timestamptz created_at
        }

        class beds {
            +integer bed_id [PK]
            +text greenhouse_id [FK]
            +text zone
            +text crop
            +text growth_stage
            +boolean harvestable
            +boolean robot_accessible
            +timestamptz updated_at
        }

        class robots {
            +text robot_id [PK]
            +text display_name
            +text status
            +integer current_bed_id [FK]
            +integer battery_percent
            +timestamptz updated_at
        }

        class actuators {
            +text actuator_id [PK]
            +text greenhouse_id [FK]
            +text actuator_type
            +text status
            +timestamptz updated_at
        }

        class chat_sessions {
            +text session_id [PK]
            +text user_id
            +text unreal_client_id
            +timestamptz created_at
        }

        class chat_messages {
            +text message_id [PK]
            +text session_id [FK]
            +text role
            +text content
            +text correlation_id
            +timestamptz created_at
        }

        class robot_commands {
            +text command_id [PK]
            +text session_id [FK]
            +text command_name
            +text correlation_id
            +text idempotency_key [UNIQUE]
            +jsonb parameters
            +text status
            +timestamptz created_at
            +timestamptz updated_at
        }

        class control_tasks {
            +text task_id [PK]
            +text command_name
            +text target_type
            +text target_id
            +text correlation_id
            +text idempotency_key [UNIQUE]
            +jsonb parameters
            +text status
            +timestamptz created_at
            +timestamptz updated_at
        }

        class domain_events {
            +text event_id [PK]
            +text event_type
            +text correlation_id
            +text session_id
            +text command_id
            +timestamptz occurred_at
            +jsonb payload
        }
    end

    %% Relationships in PostgreSQL
    greenhouses "1" --> "0..*" beds : contains
    greenhouses "1" --> "0..*" actuators : operates
    beds "1" --> "0..*" robots : current location
    chat_sessions "1" --> "0..*" chat_messages : records
    chat_sessions "1" --> "0..*" robot_commands : issues

    %% ----------------------------------------------------
    %% TimescaleDB (External Timeseries DB - Dotted)
    %% ----------------------------------------------------
    subgraph TimescaleDB ["TimescaleDB (External / Timeseries Sensor Layer)"]
        class sensor_readings external;
        class robot_state_history external;

        class sensor_readings {
            +bigint reading_id [PK]
            +text greenhouse_id
            +text sensor_id
            +text metric
            +double precision value
            +text unit
            +timestamptz measured_at [PK]
        }

        class robot_state_history {
            +bigint history_id [PK]
            +text robot_id
            +text status
            +integer bed_id
            +integer battery_percent
            +timestamptz recorded_at [PK]
        }
    end

    %% ----------------------------------------------------
    %% Qdrant (External Vector DB - Dotted)
    %% ----------------------------------------------------
    subgraph Qdrant ["Qdrant (External / Vector Document Store)"]
        class farm_operations_ko external;

        class farm_operations_ko {
            +float[768] vector
            +text document_id [Payload]
            +text title [Payload]
            +text category [Payload]
            +text language [Payload]
            +text source [Payload]
            +text content [Payload]
        }
    end

    %% ----------------------------------------------------
    %% Mock / Temporary External APIs (Dotted / Orange)
    %% ----------------------------------------------------
    subgraph MockAPIs ["GPU Farm / IoT Platform (Temporary / Mock External)"]
        class GPU_Farm tempMock;
        class Control_IoT tempMock;

        class GPU_Farm {
            <<Mock Service>>
            +STT Model API (Whisper)
            +TTS Model API (Synthesizer)
            +LLM API (Gemma-4 / Ollama)
            +Object Detection API (YOLO)
            +Embedding API
        }

        class Control_IoT {
            <<Mock Platform>>
            +Control Server tasks (/tasks)
            +IoT Device commands
            +Completed event webhook callback
        }
    end

    %% Logical flow references (DB associations to External)
    robots -.-> robot_state_history : track timeseries
    beds -.-> farm_operations_ko : semantic manual search
    robot_commands -.-> Control_IoT : execute physical command
    domain_events -.-> Control_IoT : receive status callback
    chat_messages -.-> GPU_Farm : inference / parse / synthesize
```

---

## 2. PostgreSQL Core Relational Schema

PostgreSQL serves as the main source of truth for **user session state**, **chat history**, **issuing robot commands**, and **smart farm configuration metadata** (greenhouses, beds, robots, actuators).

### 2.1. Table: `greenhouses`
Defines the boundary of physical greenhouse units.

| Column Name | Data Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `greenhouse_id` | `text` | `PRIMARY KEY` | Unique identifier for the greenhouse (e.g., `GH-ZONE-048-ALPHA`). |
| `name` | `text` | `NOT NULL` | Human-readable name of the greenhouse. |
| `location` | `text` | `NOT NULL` | Description or coordinate marker of the physical layout. |
| `created_at` | `timestamptz`| `DEFAULT now()` | Timestamp when the greenhouse record was created. |

### 2.2. Table: `beds`
Represents cultivation beds/trays within a greenhouse.

| Column Name | Data Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `bed_id` | `integer` | `PRIMARY KEY` | Unique ID of the cultivation bed. |
| `greenhouse_id` | `text` | `REFERENCES greenhouses(greenhouse_id)` | The greenhouse where this bed is located. |
| `zone` | `text` | `NOT NULL` | Zone letter/designation within the greenhouse (e.g. `A`, `Zone 1`). |
| `crop` | `text` | `NOT NULL` | The type of crop currently planted (e.g. `Strawberry`, `Tomato`). |
| `growth_stage` | `text` | `NOT NULL` | Growth phase of the crop (e.g. `seedling`, `flowering`, `mature`). |
| `harvestable` | `boolean` | `DEFAULT false` | Flag indicating whether crops are ready for harvesting. |
| `robot_accessible`| `boolean` | `DEFAULT true` | Safety flag showing if AMR robots can access the bed. |
| `updated_at` | `timestamptz`| `DEFAULT now()` | Last update timestamp of the bed status. |

### 2.3. Table: `robots`
Tracks the current operational status of autonomous mobile robots (AMRs).

| Column Name | Data Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `robot_id` | `text` | `PRIMARY KEY` | Unique ID of the robot (e.g. `AMR_1`, `AMR_H100`). |
| `display_name` | `text` | `NOT NULL` | User-friendly name displayed on the Unreal frontend. |
| `status` | `text` | `NOT NULL` | Current operational state (e.g. `idle`, `moving`, `harvesting`, `charging`). |
| `current_bed_id`| `integer` | `REFERENCES beds(bed_id)` | The bed the robot is currently positioned at (null if transitioning). |
| `battery_percent`| `integer` | `CHECK (0 <= battery_percent <= 100)` | Remaining battery capacity of the AMR. |
| `updated_at` | `timestamptz`| `DEFAULT now()` | Last status sync timestamp. |

### 2.4. Table: `actuators`
Tracks structural control actuators (e.g., nutrient valves, ventilation fans, LED lighting).

| Column Name | Data Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `actuator_id` | `text` | `PRIMARY KEY` | Unique identifier of the actuator valve/fan. |
| `greenhouse_id` | `text` | `REFERENCES greenhouses(greenhouse_id)` | Greenhouse unit containing the actuator. |
| `actuator_type` | `text` | `NOT NULL` | Type of actuator (e.g., `valve`, `fan`, `led`). |
| `status` | `text` | `NOT NULL` | On/off or detailed status (e.g., `open`, `closed`, `speed_50`). |
| `updated_at` | `timestamptz`| `DEFAULT now()` | Last sync timestamp. |

### 2.5. Table: `chat_sessions`
Manages conversation sessions between users (clients) and the AI chatbot.

| Column Name | Data Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `session_id` | `text` | `PRIMARY KEY` | Generated session ID (prefixed with `session_`). |
| `user_id` | `text` | | User account ID performing the operation. |
| `unreal_client_id`| `text` | | Unreal Engine client UUID. Used for routing events to specific viewports. |
| `created_at` | `timestamptz`| `DEFAULT now()` | Timestamp when the session was initialized. |

### 2.6. Table: `chat_messages`
Stores the multi-turn chat messages within a session.

| Column Name | Data Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `message_id` | `text` | `PRIMARY KEY` | Generated message ID (prefixed with `msg_`). |
| `session_id` | `text` | `REFERENCES chat_sessions(session_id) ON DELETE CASCADE` | Associated chat session. |
| `role` | `text` | `NOT NULL` | Actor role (e.g., `system`, `user`, `assistant`). |
| `content` | `text` | `NOT NULL` | Raw text message content or final LLM report text. |
| `correlation_id`| `text` | `NOT NULL` | Request transaction ID tracing frontend request to backend responses. |
| `created_at` | `timestamptz`| `DEFAULT now()` | Message timestamp. |

* **Indices:**
  * `idx_chat_messages_session_created_at` on `(session_id, created_at)`: Optimizes message history list queries for active sessions.

### 2.7. Table: `robot_commands`
Logs the robot commands generated by LLM tool calls. Enforces execution tracking and idempotency.

| Column Name | Data Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `command_id` | `text` | `PRIMARY KEY` | Unique command identifier (prefixed with `cmd_`). |
| `session_id` | `text` | `REFERENCES chat_sessions(session_id)` | Session triggering the action. |
| `command_name` | `text` | `NOT NULL` | Action identifier (e.g., `harvest_bed`, `move_to_bed`). |
| `correlation_id`| `text` | `NOT NULL` | Context ID mapping command lifecycle events. |
| `idempotency_key`| `text` | `UNIQUE` | Unique token generated by the client to prevent duplicate command execution. |
| `parameters` | `jsonb` | `DEFAULT '{}'::jsonb` | Task configuration arguments (e.g., `{"bed_id": 1}`). |
| `status` | `text` | `NOT NULL` | Status of the command (`pending`, `accepted`, `running`, `completed`, `failed`). |
| `created_at` | `timestamptz`| `DEFAULT now()` | Command initiation timestamp. |
| `updated_at` | `timestamptz`| `DEFAULT now()` | Last state transition update. |

### 2.8. Table: `control_tasks`
Tracks physical control tasks submitted by the chatbot backend to the Demo Control Server.

| Column Name | Data Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `task_id` | `text` | `PRIMARY KEY` | Task tracking ID generated by the control server. |
| `command_name` | `text` | `NOT NULL` | Operational command. |
| `target_type` | `text` | `NOT NULL` | Target object domain type (e.g., `bed`, `robot`). |
| `target_id` | `text` | `NOT NULL` | Target object identifier. |
| `correlation_id`| `text` | `NOT NULL` | Trace ID. |
| `idempotency_key`| `text` | `UNIQUE` | Client token ensuring task execution safety. |
| `parameters` | `jsonb` | `DEFAULT '{}'::jsonb` | Execution parameters. |
| `status` | `text` | `NOT NULL` | Status of the task inside the control server. |
| `created_at` | `timestamptz`| `DEFAULT now()` | Creation time. |
| `updated_at` | `timestamptz`| `DEFAULT now()` | Last execution heartbeat updates. |

### 2.9. Table: `domain_events`
Audit trail recording robot events, state changes, and IoT reports.

| Column Name | Data Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `event_id` | `text` | `PRIMARY KEY` | Event identifier. |
| `event_type` | `text` | `NOT NULL` | Category name (e.g. `robot_command_completed`, `sensor_anomaly`). |
| `correlation_id`| `text` | `NOT NULL` | Correlated transaction ID. |
| `session_id` | `text` | | Target chat session ID (optional). |
| `command_id` | `text` | | Correlated command ID (optional). |
| `occurred_at` | `timestamptz`| `DEFAULT now()` | Timestamp when the event was emitted. |
| `payload` | `jsonb` | `DEFAULT '{}'::jsonb` | Structured details of the event (e.g., `{"result": "success"}`). |

---

## 3. TimescaleDB Schema (External Layer)

TimescaleDB manages high-frequency, time-series telemetry data from greenhouse environmental sensors and AMR hardware logs.

### 3.1. Hypertable: `sensor_readings`
Records timeseries ambient environment logs (temperature, humidity, CO2, illuminance).

| Column Name | Data Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `reading_id` | `bigint` | `IDENTITY PRIMARY KEY [Part 1]` | Auto-incrementing identifier. |
| `greenhouse_id` | `text` | `NOT NULL` | Source greenhouse. |
| `sensor_id` | `text` | `NOT NULL` | Physical sensor ID (e.g., `Z1_SENSOR_01`). |
| `metric` | `text` | `NOT NULL` | Name of metric (e.g. `TEMPERATURE`, `HUMIDITY`, `CO2`). |
| `value` | `double precision`| `NOT NULL` | Numeric measurement value. |
| `unit` | `text` | `NOT NULL` | Measurement unit (e.g. `℃`, `%`, `ppm`, `lux`). |
| `measured_at` | `timestamptz`| `PRIMARY KEY [Part 2]` | Timestamp of the telemetry read. Part of hypertable range. |

* **Hypertable configuration:** Partitioned by `measured_at` in intervals.
* **Indices:**
  * `idx_sensor_readings_metric_time` on `(metric, measured_at DESC)`: Optimized for dashboard graphs retrieving latest metrics.

### 3.2. Hypertable: `robot_state_history`
Maintains operational tracking history for robot status and telemetry.

| Column Name | Data Type | Constraints | Description |
| :--- | :--- | :--- | :--- |
| `history_id` | `bigint` | `IDENTITY PRIMARY KEY [Part 1]` | History event index. |
| `robot_id` | `text` | `NOT NULL` | Target robot ID. |
| `status` | `text` | `NOT NULL` | Robot status during report. |
| `bed_id` | `integer` | | Target bed ID. |
| `battery_percent`| `integer` | `CHECK (0 <= battery_percent <= 100)` | Remaining battery capacity. |
| `recorded_at` | `timestamptz`| `PRIMARY KEY [Part 2]` | Capture timestamp. Hypertable range key. |

* **Hypertable configuration:** Partitioned by `recorded_at`.

---

## 4. Qdrant Collection Schema (Vector Layer)

Used by the RAG (Retrieval-Augmented Generation) agent to search agricultural operation manuals, failure guides, and guidelines.

### Collection Name: `farm_operations_ko`
* **Vector Configuration:**
  * **Dimensions:** 768 (Standard size matching modern embedding models, e.g., KoSimCSE or BGE-ko).
  * **Metric:** Cosine (Calculates similarity index between query vector and database document vectors).
* **Payload Metadata Schema:**
  * `document_id` (`keyword`): Unique ID of the document chunk.
  * `title` (`text`): Title of the manual or guide chapter.
  * `category` (`keyword`): Classification (e.g., `harvest`, `failure`, `grow_guide`).
  * `language` (`keyword`): Target language code (e.g., `ko`, `en`).
  * `source` (`keyword`): Filename or URL where the text originated.
  * `content` (`text`): Raw text chunk containing manual information.

---

## 5. Typical Data Flow Scenarios

### 5.1. Multi-turn Chat & RAG Workflow
```
[User Message] ---> /chat/messages (FastAPI) 
                     |
                     +---> Embedding Generation (/ai-server/inference/embeddings)
                     |       |
                     |       v (Query Vector)
                     +---> Vector Search ---> Qdrant (Retrieval of matches)
                     |                          |
                     |                          v (Manual Content Chunks)
                     +---> Prompt Composition --+
                     |
                     v
             [GPU Farm (LLM)] ---> Stream tokens back to client
```

### 5.2. Idempotent Robot Command Flow
```
[User Request] ---> LLM tool planning ---> [Create robot_commands (status: pending)]
                                            |
                                            v
                                   Check idempotency_key
                                            |
                       [Duplicate] <--------+--------> [New Command]
                            |                                |
                   Return cached response                    v
                                                   Publish command task to Control Server
                                                   Update status: running
                                                             |
                                                             v (Time passes / Async execution)
                                                   IoT Platform callback -> /events/robot-command
                                                             |
                                                             v
                                                   Write domain_events audit
                                                   Update status: completed
                                                   Trigger LLM to generate report
                                                   Send report message via WebSocket to Unreal
```

### 5.3. Time-series Sensor Logging
```
[Physical Sensors] ---> IoT Platform MQTT/HTTP ---> TimescaleDB (sensor_readings)
                                                     |
                                                     v (Periodic Polling / Stream)
                                            /dashboard/overlay (FastAPI query latest values)
                                                     |
                                                     v
                                            Unreal Engine Dashboard UI
```
