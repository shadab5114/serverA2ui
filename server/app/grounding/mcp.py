"""The design system's catalog MCP server (open decision D3), via langchain-mcp-adapters.

The server (D:/DesignSystem/pds/mcp/catalog-server.mjs) speaks MCP Streamable HTTP
at MCP_URL. If nothing answers there and MCP_SERVER_SCRIPT is set, the backend
starts it as a managed child process (`node <script>`), pointed at the SAME
catalog.json the validator gate uses (PDS_CATALOG_PATH), so the components the
brief suggests are exactly the ones the gate accepts. It is stopped on shutdown.

Unavailable MCP never breaks a turn: calls return {answer: "", sources: [], note}.
Tools used: resolve_intent_to_schema (intent -> matched components).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..config import settings
from .sources import GroundingResult, Source

SERVER_NAME = "pds-catalog"


class CatalogMcp:
    name = "mcp.pds-catalog"

    def __init__(self, url: str | None = None, script: os.PathLike | None = None) -> None:
        self.url = url if url is not None else settings.mcp_url
        self.script = script if script is not None else settings.mcp_server_script
        self._process: subprocess.Popen | None = None
        self._tools: dict[str, Any] = {}
        self.status = "not started"

    # --- lifecycle ------------------------------------------------------------

    async def _reachable(self) -> bool:
        if not self.url:
            return False
        u = urlsplit(self.url)
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                await client.get(f"{u.scheme}://{u.netloc}/")
            return True
        except httpx.HTTPError:
            return False

    def _spawn(self) -> None:
        u = urlsplit(self.url or "")
        env = {**os.environ, "PORT": str(u.port or 3939), "PDS_CATALOG_PATH": str(settings.catalog_path)}
        # subprocess.Popen, not asyncio's: the Windows Selector loop can't run subprocesses.
        self._process = subprocess.Popen(
            ["node", str(self.script)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    async def start(self) -> str:
        """Connect (spawning the server first if configured). Returns a one-line status."""
        if not self.url:
            self.status = "off (MCP_URL not set)"
            return self.status
        spawned = False
        if not await self._reachable() and self.script:
            self._spawn()
            spawned = True
            for _ in range(40):  # up to ~10 s for node to boot
                await asyncio.sleep(0.25)
                if await self._reachable():
                    break
        if not await self._reachable():
            self.status = f"unavailable at {self.url}" + (" (spawn failed)" if spawned else "")
            return self.status
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient

            client = MultiServerMCPClient({SERVER_NAME: {"transport": "streamable_http", "url": self.url}})
            self._tools = {t.name: t for t in await client.get_tools()}
        except Exception as err:  # noqa: BLE001
            self.status = f"connect failed at {self.url}: {err}"
            return self.status
        how = f"spawned {self.script}" if spawned else "already running"
        self.status = f"{self.url} ({how}; tools: {', '.join(sorted(self._tools))})"
        return self.status

    async def stop(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()

    @property
    def available(self) -> bool:
        return "resolve_intent_to_schema" in self._tools

    # --- tools ----------------------------------------------------------------

    async def resolve_intent(self, intent: str, limit: int = 5) -> GroundingResult:
        """Components the catalog server matches to an intent, as citable sources."""
        if not self.available:
            return GroundingResult("", [], note=f"MCP {self.status}")
        raw = await self._tools["resolve_intent_to_schema"].ainvoke({"intent": intent, "limit": limit})
        body = _json_from_tool(raw)
        matched = body.get("matched") or []
        components = body.get("components") or {}
        sources = []
        for m in matched:
            name = m.get("name") if isinstance(m, dict) else str(m)
            schema = components.get(name) or {}
            sources.append(Source(f"mcp:{name}", name, str(schema.get("description") or ""), f"mcp:{SERVER_NAME}"))
        answer = "; ".join(f"{s.title}: {s.text}" for s in sources)
        return GroundingResult(answer, sources, "" if sources else "no components matched")


def _json_from_tool(raw: Any) -> dict[str, Any]:
    """MCP tool results arrive as a JSON string, a content-block list, or (content, artifact)."""
    if isinstance(raw, tuple):
        raw = raw[0]
    if isinstance(raw, list):
        raw = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in raw)
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, dict) else {}
