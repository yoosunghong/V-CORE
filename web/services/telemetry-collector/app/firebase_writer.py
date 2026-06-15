from __future__ import annotations

import logging
import os
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class TelemetrySink(Protocol):
    """Anything the collector can push a telemetry node into (Firebase or a fake)."""

    def write(self, path: str, data: dict[str, Any]) -> None: ...


class NullSink:
    """Used when Firebase is not configured so the demo stays up without credentials."""

    def write(self, path: str, data: dict[str, Any]) -> None:
        logger.debug("Firebase not configured; dropping write to %s", path)


class FirebaseSink:
    """Writes telemetry nodes into Firebase Realtime Database via firebase-admin.

    Credentials come from the standard GOOGLE_APPLICATION_CREDENTIALS service-account
    file; the database URL from FIREBASE_DB_URL. `db.reference(path).set(...)` is a
    blocking call, so the collector runs it in an executor off the event loop.
    """

    def __init__(self, database_url: str, credentials_path: str | None = None) -> None:
        import firebase_admin
        from firebase_admin import credentials, db

        if not firebase_admin._apps:
            cred = (
                credentials.Certificate(credentials_path)
                if credentials_path
                else credentials.ApplicationDefault()
            )
            firebase_admin.initialize_app(cred, {"databaseURL": database_url})
        self._db = db

    def write(self, path: str, data: dict[str, Any]) -> None:
        self._db.reference(path).set(data)


def build_sink() -> TelemetrySink:
    """Construct a Firebase sink from env, falling back to a no-op sink on any problem."""
    database_url = os.getenv("FIREBASE_DB_URL", "").strip()
    if not database_url:
        logger.warning("FIREBASE_DB_URL unset; telemetry will not be persisted to Firebase")
        return NullSink()
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip() or None
    try:
        sink = FirebaseSink(database_url, credentials_path)
        logger.info("Firebase Realtime Database sink ready (%s)", database_url)
        return sink
    except Exception as exc:  # noqa: BLE001 - demo must not crash if creds are bad
        logger.error("Failed to init Firebase sink (%s); using no-op sink", exc)
        return NullSink()
