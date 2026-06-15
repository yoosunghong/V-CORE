from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.infrastructure.container import AppContainer

router = APIRouter()


@router.websocket("/chat/sessions/{session_id}/events")
async def session_events(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    container: AppContainer = websocket.app.state.container
    if await container.repository.get(session_id) is None:
        await websocket.close(code=4404, reason="Unknown session")
        return

    for event in await container.events.history(session_id):
        await websocket.send_json(event.model_dump(mode="json"))

    queue = await container.events.subscribe(session_id)
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event.model_dump(mode="json"))
    except (WebSocketDisconnect, asyncio.CancelledError):
        await container.events.unsubscribe(session_id, queue)
