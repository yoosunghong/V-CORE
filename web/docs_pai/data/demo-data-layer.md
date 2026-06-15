# Demo Data Layer

## Relational Schema

PostgreSQL stores low-cardinality domain and workflow state:

- `greenhouses`: demo greenhouse identity and location.
- `beds`: crop, growth stage, harvestability, zone, and robot accessibility.
- `robots`: current robot status and battery snapshot.
- `actuators`: demo actuator state.
- `chat_sessions`: chatbot session identity for command traceability.
- `robot_commands`: command lifecycle, correlation id, idempotency key, and parameters.
- `control_tasks`: control-server task boundary for handoff demonstrations.
- `domain_events`: command, robot, chat, and control events as JSON payloads.

## Vector Collection

Qdrant collection `farm_operations_ko` is reserved for Korean operation manuals,
robot task guides, crop care notes, and handoff documents. The initial vector size
is `768` so a local embedding model or hosted embedding gateway can be attached
without changing collection names.

## Timeseries Schema

TimescaleDB stores append-only telemetry:

- `sensor_readings`: temperature, humidity, CO2, illuminance, and future sensor metrics.
- `robot_state_history`: robot movement/work status snapshots for Unreal replay and audits.

The sample data seed creates recent 24-hour readings at 5-minute intervals.
