"""Checkpointer selection (reference: agent/checkpointer.js).

Postgres (durable, survives restarts) when DATABASE_URL is set, else an in-memory
saver (lost on restart). The Postgres saver owns a connection, so it is opened as
an async context and kept open for the app lifetime (FastAPI lifespan).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import urlsplit

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver


@dataclass(frozen=True)
class Checkpointer:
    saver: BaseCheckpointSaver
    kind: str  # "postgres" | "memory"
    detail: str


def _describe(url: str) -> str:
    """host/db without credentials."""
    try:
        u = urlsplit(url)
        return f"postgres {u.hostname}:{u.port or 5432}{u.path}"
    except ValueError:
        return "postgres"


@asynccontextmanager
async def open_checkpointer(database_url: str | None) -> AsyncIterator[Checkpointer]:
    if not database_url:
        yield Checkpointer(InMemorySaver(), "memory", "in-memory (no DATABASE_URL)")
        return

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with AsyncPostgresSaver.from_conn_string(database_url) as saver:
        await saver.setup()  # create checkpoint tables if they don't exist yet
        yield Checkpointer(saver, "postgres", _describe(database_url))
