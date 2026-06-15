from __future__ import annotations

from app.application.ports import SessionRepository
from app.domain.models import ChatMessage, ChatSession, ChatSessionSummary


class SessionService:
    def __init__(self, repository: SessionRepository) -> None:
        self._repository = repository

    async def create_session(
        self,
        user_id: str | None = None,
        unreal_client_id: str | None = None,
    ) -> ChatSession:
        return await self._repository.create(
            ChatSession(user_id=user_id, unreal_client_id=unreal_client_id)
        )

    async def require_session(self, session_id: str) -> ChatSession:
        session = await self._repository.get(session_id)
        if session is None:
            raise ValueError(f"Unknown chat session: {session_id}")
        return session

    async def delete_session(self, session_id: str) -> None:
        await self.require_session(session_id)
        await self._repository.delete(session_id)

    async def list_sessions(
        self,
        user_id: str | None = None,
        unreal_client_id: str | None = None,
        limit: int = 20,
    ) -> list[ChatSessionSummary]:
        return await self._repository.list_sessions(
            user_id=user_id,
            unreal_client_id=unreal_client_id,
            limit=limit,
        )

    async def list_messages(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[ChatMessage]:
        await self.require_session(session_id)
        return await self._repository.list_messages(session_id, limit=limit)
