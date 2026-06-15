from __future__ import annotations

import asyncio
from typing import Any

from app.domain.models import (
    ChatMessage,
    ChatSession,
    ChatSessionSummary,
    CommandStatus,
    MessageRole,
    RobotCommand,
    RobotCommandName,
    SimulationRun,
    SimulationRunStatus,
    Simulation,
    utc_now,
)


class InMemorySessionRepository:
    def __init__(self) -> None:
        self._sessions: dict[str, ChatSession] = {}
        self._messages: dict[str, list[ChatMessage]] = {}
        self._commands: dict[str, RobotCommand] = {}
        self._simulations: dict[str, Simulation] = {}
        self._runs: dict[str, SimulationRun] = {}

    async def create(self, session: ChatSession) -> ChatSession:
        self._sessions[session.session_id] = session
        self._messages.setdefault(session.session_id, [])
        return session

    async def get(self, session_id: str) -> ChatSession | None:
        return self._sessions.get(session_id)

    async def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        self._messages.pop(session_id, None)
        self._commands = {
            command_id: command
            for command_id, command in self._commands.items()
            if command.session_id != session_id
        }

    async def list_sessions(
        self,
        user_id: str | None = None,
        unreal_client_id: str | None = None,
        limit: int = 20,
    ) -> list[ChatSessionSummary]:
        sessions = [
            session
            for session in self._sessions.values()
            if (user_id is None or session.user_id == user_id)
            and (unreal_client_id is None or session.unreal_client_id == unreal_client_id)
        ]
        summaries: list[ChatSessionSummary] = []
        for session in sessions:
            messages = self._messages.get(session.session_id, [])
            if not messages:
                continue
            last_message = messages[-1] if messages else None
            first_user_message = next(
                (message for message in messages if message.role == MessageRole.USER),
                None,
            )
            summaries.append(
                ChatSessionSummary(
                    **session.model_dump(),
                    message_count=len(messages),
                    last_message_at=last_message.created_at if last_message else None,
                    last_message_preview=last_message.content[:80] if last_message else None,
                    first_user_message_preview=first_user_message.content[:80]
                    if first_user_message
                    else None,
                )
            )
        return sorted(
            summaries,
            key=lambda item: item.last_message_at or item.created_at,
            reverse=True,
        )[:limit]

    async def add_message(self, message: ChatMessage) -> ChatMessage:
        self._messages.setdefault(message.session_id, []).append(message)
        return message

    async def list_messages(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[ChatMessage]:
        messages = list(self._messages.get(session_id, []))
        if limit is not None:
            return messages[-limit:]
        return messages

    async def list_commands(self, session_id: str) -> list[RobotCommand]:
        return [
            command
            for command in self._commands.values()
            if command.session_id == session_id
        ]

    async def save_command(self, command: RobotCommand) -> RobotCommand:
        existing = await self.get_command_by_idempotency_key(command.idempotency_key)
        if existing is not None:
            return existing
        self._commands[command.command_id] = command
        return command

    async def get_command(self, command_id: str) -> RobotCommand | None:
        return self._commands.get(command_id)

    async def get_command_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> RobotCommand | None:
        return next(
            (
                command
                for command in self._commands.values()
                if command.idempotency_key == idempotency_key
            ),
            None,
        )

    async def update_command(self, command: RobotCommand) -> RobotCommand:
        self._commands[command.command_id] = command
        return command

    async def list_simulations(self) -> list[Simulation]:
        return sorted(self._simulations.values(), key=lambda item: item.created_at, reverse=True)

    async def create_simulation(self, simulation: Simulation) -> Simulation:
        self._simulations[simulation.simulation_id] = simulation
        return simulation

    async def get_simulation(self, simulation_id: str) -> Simulation | None:
        return self._simulations.get(simulation_id)

    async def update_simulation(self, simulation: Simulation) -> Simulation:
        simulation.updated_at = utc_now()
        self._simulations[simulation.simulation_id] = simulation
        return simulation

    async def delete_simulation(self, simulation_id: str) -> None:
        self._simulations.pop(simulation_id, None)
        self._runs = {
            run_id: run for run_id, run in self._runs.items() if run.simulation_id != simulation_id
        }

    async def create_run(self, run: SimulationRun) -> SimulationRun:
        self._runs[run.run_id] = run
        return run

    async def get_run(self, run_id: str) -> SimulationRun | None:
        return self._runs.get(run_id)

    async def list_runs(self, simulation_id: str | None = None) -> list[SimulationRun]:
        runs = [
            run
            for run in self._runs.values()
            if simulation_id is None or run.simulation_id == simulation_id
        ]
        return sorted(runs, key=lambda item: item.created_at, reverse=True)

    async def update_run(self, run: SimulationRun) -> SimulationRun:
        run.updated_at = utc_now()
        self._runs[run.run_id] = run
        return run

    async def update_run_status(
        self,
        run_id: str,
        status: SimulationRunStatus,
        result_json: dict[str, Any] | None = None,
        kpis_json: dict[str, Any] | None = None,
    ) -> SimulationRun | None:
        run = self._runs.get(run_id)
        if run is None:
            return None
        run.status = status
        run.updated_at = utc_now()
        if status in {SimulationRunStatus.RUNNING, SimulationRunStatus.STARTING} and run.started_at is None:
            run.started_at = utc_now()
        if status in {
            SimulationRunStatus.STOPPED,
            SimulationRunStatus.COMPLETED,
            SimulationRunStatus.FAILED,
        }:
            run.ended_at = utc_now()
        if result_json is not None:
            run.result_json = result_json
        if kpis_json is not None:
            run.kpis_json = kpis_json
        return run


class PostgresSessionRepository:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._schema_ready = False
        self._schema_lock = asyncio.Lock()

    async def _connect(self):
        try:
            from psycopg import AsyncConnection
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL repository requires psycopg. Install dependencies from requirements.txt."
            ) from exc
        return await AsyncConnection.connect(self._database_url)

    async def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        async with self._schema_lock:
            if self._schema_ready:
                return
            async with await self._connect() as conn:
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chat_sessions (
                      session_id text PRIMARY KEY,
                      user_id text,
                      unreal_client_id text,
                      created_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS chat_messages (
                      message_id text PRIMARY KEY,
                      session_id text NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
                      role text NOT NULL,
                      content text NOT NULL,
                      correlation_id text NOT NULL,
                      created_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
                await conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created_at
                      ON chat_messages(session_id, created_at)
                    """
                )
                await conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_created_at
                      ON chat_sessions(user_id, created_at DESC)
                    """
                )
                await conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_chat_sessions_unreal_client_created_at
                      ON chat_sessions(unreal_client_id, created_at DESC)
                    """
                )
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS robot_commands (
                      command_id text PRIMARY KEY,
                      session_id text REFERENCES chat_sessions(session_id),
                      command_name text NOT NULL,
                      correlation_id text NOT NULL,
                      idempotency_key text NOT NULL UNIQUE,
                      parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
                      status text NOT NULL,
                      created_at timestamptz NOT NULL DEFAULT now(),
                      updated_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS simulation_scenarios (
                      scenario_id text PRIMARY KEY,
                      name text NOT NULL,
                      agv_count integer NOT NULL,
                      speed_multiplier double precision NOT NULL,
                      workload_percent double precision NOT NULL,
                      policy_id text NOT NULL,
                      duration_seconds integer NOT NULL,
                      bottleneck_threshold_sec double precision NOT NULL,
                      created_at timestamptz NOT NULL DEFAULT now(),
                      updated_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
                await conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS simulation_runs (
                      run_id text PRIMARY KEY,
                      scenario_id text NOT NULL REFERENCES simulation_scenarios(scenario_id) ON DELETE CASCADE,
                      status text NOT NULL,
                      ue_run_id text,
                      speed_multiplier double precision NOT NULL,
                      started_at timestamptz,
                      ended_at timestamptz,
                      result_json jsonb,
                      kpis_json jsonb,
                      created_at timestamptz NOT NULL DEFAULT now(),
                      updated_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
                await conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_simulation_runs_simulation_created_at
                      ON simulation_runs(scenario_id, created_at DESC)
                    """
                )
            self._schema_ready = True

    async def create(self, session: ChatSession) -> ChatSession:
        await self._ensure_schema()
        async with await self._connect() as conn:
            await conn.execute(
                """
                INSERT INTO chat_sessions(session_id, user_id, unreal_client_id, created_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (session_id) DO NOTHING
                """,
                (
                    session.session_id,
                    session.user_id,
                    session.unreal_client_id,
                    session.created_at,
                ),
            )
        return session

    async def get(self, session_id: str) -> ChatSession | None:
        await self._ensure_schema()
        async with await self._connect() as conn:
            cursor = await conn.execute(
                """
                SELECT session_id, user_id, unreal_client_id, created_at
                FROM chat_sessions
                WHERE session_id = %s
                """,
                (session_id,),
            )
            row = await cursor.fetchone()
        return self._session_from_row(row) if row else None

    async def delete(self, session_id: str) -> None:
        await self._ensure_schema()
        async with await self._connect() as conn:
            # robot_commands has no ON DELETE CASCADE, so clear it before the session;
            # chat_messages cascades automatically.
            await conn.execute(
                "DELETE FROM robot_commands WHERE session_id = %s",
                (session_id,),
            )
            await conn.execute(
                "DELETE FROM chat_sessions WHERE session_id = %s",
                (session_id,),
            )

    async def list_sessions(
        self,
        user_id: str | None = None,
        unreal_client_id: str | None = None,
        limit: int = 20,
    ) -> list[ChatSessionSummary]:
        await self._ensure_schema()
        predicates: list[str] = []
        params: list[Any] = []
        if user_id is not None:
            predicates.append("s.user_id = %s")
            params.append(user_id)
        if unreal_client_id is not None:
            predicates.append("s.unreal_client_id = %s")
            params.append(unreal_client_id)
        where = f"WHERE {' AND '.join(predicates)}" if predicates else ""
        params.append(limit)
        async with await self._connect() as conn:
            cursor = await conn.execute(
                f"""
                SELECT
                  s.session_id,
                  s.user_id,
                  s.unreal_client_id,
                  s.created_at,
                  COUNT(m.message_id)::int AS message_count,
                  MAX(m.created_at) AS last_message_at,
                  (
                    SELECT cm.content
                    FROM chat_messages cm
                    WHERE cm.session_id = s.session_id
                    ORDER BY cm.created_at DESC
                    LIMIT 1
                  ) AS last_message_preview,
                  (
                    SELECT cm.content
                    FROM chat_messages cm
                    WHERE cm.session_id = s.session_id
                      AND cm.role = 'user'
                    ORDER BY cm.created_at ASC
                    LIMIT 1
                  ) AS first_user_message_preview
                FROM chat_sessions s
                LEFT JOIN chat_messages m ON m.session_id = s.session_id
                {where}
                GROUP BY s.session_id, s.user_id, s.unreal_client_id, s.created_at
                HAVING COUNT(m.message_id) > 0
                ORDER BY COALESCE(MAX(m.created_at), s.created_at) DESC
                LIMIT %s
                """,
                params,
            )
            rows = await cursor.fetchall()
        return [
            ChatSessionSummary(
                session_id=row[0],
                user_id=row[1],
                unreal_client_id=row[2],
                created_at=row[3],
                message_count=row[4],
                last_message_at=row[5],
                last_message_preview=(row[6] or "")[:80] if row[6] else None,
                first_user_message_preview=(row[7] or "")[:80] if row[7] else None,
            )
            for row in rows
        ]

    async def add_message(self, message: ChatMessage) -> ChatMessage:
        await self._ensure_schema()
        async with await self._connect() as conn:
            await conn.execute(
                """
                INSERT INTO chat_messages(message_id, session_id, role, content, correlation_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (message_id) DO NOTHING
                """,
                (
                    message.message_id,
                    message.session_id,
                    message.role.value,
                    message.content,
                    message.correlation_id,
                    message.created_at,
                ),
            )
        return message

    async def list_messages(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[ChatMessage]:
        await self._ensure_schema()
        bounded_limit = max(limit, 1) if limit is not None else None
        limit_clause = "ORDER BY created_at DESC LIMIT %s" if bounded_limit is not None else "ORDER BY created_at ASC"
        params: tuple[Any, ...] = (session_id, bounded_limit) if bounded_limit is not None else (session_id,)
        async with await self._connect() as conn:
            cursor = await conn.execute(
                f"""
                SELECT message_id, session_id, role, content, correlation_id, created_at
                FROM chat_messages
                WHERE session_id = %s
                {limit_clause}
                """,
                params,
            )
            rows = await cursor.fetchall()
        messages = [self._message_from_row(row) for row in rows]
        if bounded_limit is not None:
            return list(reversed(messages))
        return messages

    async def list_commands(self, session_id: str) -> list[RobotCommand]:
        await self._ensure_schema()
        async with await self._connect() as conn:
            cursor = await conn.execute(
                """
                SELECT command_id, session_id, command_name, correlation_id, idempotency_key,
                       parameters, status, created_at
                FROM robot_commands
                WHERE session_id = %s
                ORDER BY created_at ASC
                """,
                (session_id,),
            )
            rows = await cursor.fetchall()
        return [self._command_from_row(row) for row in rows]

    async def save_command(self, command: RobotCommand) -> RobotCommand:
        await self._ensure_schema()
        existing = await self.get_command_by_idempotency_key(command.idempotency_key)
        if existing is not None:
            return existing
        async with await self._connect() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO robot_commands(
                  command_id, session_id, command_name, correlation_id, idempotency_key,
                  parameters, status, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, now())
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING command_id, session_id, command_name, correlation_id, idempotency_key,
                          parameters, status, created_at
                """,
                (
                    command.command_id,
                    command.session_id,
                    command.command_name.value,
                    command.correlation_id,
                    command.idempotency_key,
                    self._json_dumps(command.parameters),
                    command.status.value,
                    command.created_at,
                ),
            )
            row = await cursor.fetchone()
        if row:
            return self._command_from_row(row)
        existing = await self.get_command_by_idempotency_key(command.idempotency_key)
        return existing if existing is not None else command

    async def get_command(self, command_id: str) -> RobotCommand | None:
        await self._ensure_schema()
        async with await self._connect() as conn:
            cursor = await conn.execute(
                """
                SELECT command_id, session_id, command_name, correlation_id, idempotency_key,
                       parameters, status, created_at
                FROM robot_commands
                WHERE command_id = %s
                """,
                (command_id,),
            )
            row = await cursor.fetchone()
        return self._command_from_row(row) if row else None

    async def get_command_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> RobotCommand | None:
        await self._ensure_schema()
        async with await self._connect() as conn:
            cursor = await conn.execute(
                """
                SELECT command_id, session_id, command_name, correlation_id, idempotency_key,
                       parameters, status, created_at
                FROM robot_commands
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            )
            row = await cursor.fetchone()
        return self._command_from_row(row) if row else None

    async def update_command(self, command: RobotCommand) -> RobotCommand:
        await self._ensure_schema()
        async with await self._connect() as conn:
            await conn.execute(
                """
                UPDATE robot_commands
                SET status = %s, parameters = %s::jsonb, updated_at = now()
                WHERE command_id = %s
                """,
                (
                    command.status.value,
                    self._json_dumps(command.parameters),
                    command.command_id,
                ),
            )
        return command

    async def list_simulations(self) -> list[Simulation]:
        await self._ensure_schema()
        async with await self._connect() as conn:
            cursor = await conn.execute(
                """
                SELECT scenario_id, name, agv_count, speed_multiplier, workload_percent,
                       policy_id, duration_seconds, bottleneck_threshold_sec,
                       created_at, updated_at
                FROM simulation_scenarios
                ORDER BY created_at DESC
                """
            )
            rows = await cursor.fetchall()
        return [self._simulation_from_row(row) for row in rows]

    async def create_simulation(self, simulation: Simulation) -> Simulation:
        await self._ensure_schema()
        async with await self._connect() as conn:
            await conn.execute(
                """
                INSERT INTO simulation_scenarios(
                  scenario_id, name, agv_count, speed_multiplier, workload_percent,
                  policy_id, duration_seconds, bottleneck_threshold_sec, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    simulation.simulation_id,
                    simulation.name,
                    simulation.agv_count,
                    simulation.speed_multiplier,
                    simulation.workload_percent,
                    simulation.policy_id,
                    simulation.duration_seconds,
                    simulation.bottleneck_threshold_sec,
                    simulation.created_at,
                    simulation.updated_at,
                ),
            )
        return simulation

    async def get_simulation(self, simulation_id: str) -> Simulation | None:
        await self._ensure_schema()
        async with await self._connect() as conn:
            cursor = await conn.execute(
                """
                SELECT scenario_id, name, agv_count, speed_multiplier, workload_percent,
                       policy_id, duration_seconds, bottleneck_threshold_sec,
                       created_at, updated_at
                FROM simulation_scenarios
                WHERE scenario_id = %s
                """,
                (simulation_id,),
            )
            row = await cursor.fetchone()
        return self._simulation_from_row(row) if row else None

    async def update_simulation(self, simulation: Simulation) -> Simulation:
        await self._ensure_schema()
        simulation.updated_at = utc_now()
        async with await self._connect() as conn:
            await conn.execute(
                """
                UPDATE simulation_scenarios
                SET name = %s,
                    agv_count = %s,
                    speed_multiplier = %s,
                    workload_percent = %s,
                    policy_id = %s,
                    duration_seconds = %s,
                    bottleneck_threshold_sec = %s,
                    updated_at = %s
                WHERE scenario_id = %s
                """,
                (
                    simulation.name,
                    simulation.agv_count,
                    simulation.speed_multiplier,
                    simulation.workload_percent,
                    simulation.policy_id,
                    simulation.duration_seconds,
                    simulation.bottleneck_threshold_sec,
                    simulation.updated_at,
                    simulation.simulation_id,
                ),
            )
        return simulation

    async def delete_simulation(self, simulation_id: str) -> None:
        await self._ensure_schema()
        async with await self._connect() as conn:
            await conn.execute(
                "DELETE FROM simulation_scenarios WHERE scenario_id = %s",
                (simulation_id,),
            )

    async def create_run(self, run: SimulationRun) -> SimulationRun:
        await self._ensure_schema()
        async with await self._connect() as conn:
            await conn.execute(
                """
                INSERT INTO simulation_runs(
                  run_id, scenario_id, status, ue_run_id, speed_multiplier,
                  started_at, ended_at, result_json, kpis_json, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
                """,
                (
                    run.run_id,
                    run.simulation_id,
                    run.status.value,
                    run.ue_run_id,
                    run.speed_multiplier,
                    run.started_at,
                    run.ended_at,
                    self._json_dumps(run.result_json) if run.result_json is not None else None,
                    self._json_dumps(run.kpis_json) if run.kpis_json is not None else None,
                    run.created_at,
                    run.updated_at,
                ),
            )
        return run

    async def get_run(self, run_id: str) -> SimulationRun | None:
        await self._ensure_schema()
        async with await self._connect() as conn:
            cursor = await conn.execute(
                """
                SELECT run_id, scenario_id, status, ue_run_id, speed_multiplier,
                       started_at, ended_at, result_json, kpis_json, created_at, updated_at
                FROM simulation_runs
                WHERE run_id = %s
                """,
                (run_id,),
            )
            row = await cursor.fetchone()
        return self._run_from_row(row) if row else None

    async def list_runs(self, simulation_id: str | None = None) -> list[SimulationRun]:
        await self._ensure_schema()
        where = "WHERE scenario_id = %s" if simulation_id is not None else ""
        params: tuple[Any, ...] = (simulation_id,) if simulation_id is not None else ()
        async with await self._connect() as conn:
            cursor = await conn.execute(
                f"""
                SELECT run_id, scenario_id, status, ue_run_id, speed_multiplier,
                       started_at, ended_at, result_json, kpis_json, created_at, updated_at
                FROM simulation_runs
                {where}
                ORDER BY created_at DESC
                """,
                params,
            )
            rows = await cursor.fetchall()
        return [self._run_from_row(row) for row in rows]

    async def update_run(self, run: SimulationRun) -> SimulationRun:
        await self._ensure_schema()
        run.updated_at = utc_now()
        async with await self._connect() as conn:
            await conn.execute(
                """
                UPDATE simulation_runs
                SET status = %s,
                    ue_run_id = %s,
                    speed_multiplier = %s,
                    started_at = %s,
                    ended_at = %s,
                    result_json = %s::jsonb,
                    kpis_json = %s::jsonb,
                    updated_at = %s
                WHERE run_id = %s
                """,
                (
                    run.status.value,
                    run.ue_run_id,
                    run.speed_multiplier,
                    run.started_at,
                    run.ended_at,
                    self._json_dumps(run.result_json) if run.result_json is not None else None,
                    self._json_dumps(run.kpis_json) if run.kpis_json is not None else None,
                    run.updated_at,
                    run.run_id,
                ),
            )
        return run

    async def update_run_status(
        self,
        run_id: str,
        status: SimulationRunStatus,
        result_json: dict[str, Any] | None = None,
        kpis_json: dict[str, Any] | None = None,
    ) -> SimulationRun | None:
        run = await self.get_run(run_id)
        if run is None:
            return None
        run.status = status
        if status in {SimulationRunStatus.STARTING, SimulationRunStatus.RUNNING} and run.started_at is None:
            run.started_at = utc_now()
        if status in {
            SimulationRunStatus.STOPPED,
            SimulationRunStatus.COMPLETED,
            SimulationRunStatus.FAILED,
        }:
            run.ended_at = utc_now()
        if result_json is not None:
            run.result_json = result_json
        if kpis_json is not None:
            run.kpis_json = kpis_json
        return await self.update_run(run)

    def _session_from_row(self, row: Any) -> ChatSession:
        return ChatSession(
            session_id=row[0],
            user_id=row[1],
            unreal_client_id=row[2],
            created_at=row[3],
        )

    def _message_from_row(self, row: Any) -> ChatMessage:
        return ChatMessage(
            message_id=row[0],
            session_id=row[1],
            role=MessageRole(row[2]),
            content=row[3],
            correlation_id=row[4],
            created_at=row[5],
        )

    def _command_from_row(self, row: Any) -> RobotCommand:
        return RobotCommand(
            command_id=row[0],
            session_id=row[1],
            command_name=RobotCommandName(row[2]),
            correlation_id=row[3],
            idempotency_key=row[4],
            parameters=row[5],
            status=CommandStatus(row[6]),
            created_at=row[7],
        )

    def _json_dumps(self, value: dict[str, Any]) -> str:
        import json

        return json.dumps(value)

    def _simulation_from_row(self, row: Any) -> Simulation:
        return Simulation(
            simulation_id=row[0],
            name=row[1],
            agv_count=row[2],
            speed_multiplier=row[3],
            workload_percent=row[4],
            policy_id=row[5],
            duration_seconds=row[6],
            bottleneck_threshold_sec=row[7],
            created_at=row[8],
            updated_at=row[9],
        )

    def _run_from_row(self, row: Any) -> SimulationRun:
        return SimulationRun(
            run_id=row[0],
            simulation_id=row[1],
            status=SimulationRunStatus(row[2]),
            ue_run_id=row[3],
            speed_multiplier=row[4],
            started_at=row[5],
            ended_at=row[6],
            result_json=row[7],
            kpis_json=row[8],
            created_at=row[9],
            updated_at=row[10],
        )
