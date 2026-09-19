"""Settings: the root .env (shared keys) first, then server/.env (server-only overrides)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

SERVER_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SERVER_DIR.parent

load_dotenv(REPO_ROOT / ".env")
load_dotenv(SERVER_DIR / ".env", override=True)


def _int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    port: int
    llm_provider: str
    openai_model: str
    router_model: str
    openai_max_tokens: int
    anthropic_model: str
    database_url: str | None
    max_repairs: int
    catalog_path: Path
    templates_dir: Path
    data_dir: Path
    providers_dir: Path
    personas_path: Path
    guidelines_dir: Path
    rag_url: str | None
    mcp_url: str | None
    mcp_server_script: Path | None
    guideline_judge: bool
    reasoning_effort: str | None


def load_settings() -> Settings:
    return Settings(
        port=_int("AGUI_PORT", 8090),
        llm_provider=os.getenv("LLM_PROVIDER", "openai").strip() or "openai",
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o").strip() or "gpt-4o",
        # Same fallback chain as agent/graph.js: ROUTER_MODEL, then OPENAI_MODEL, then gpt-4o-mini.
        router_model=(os.getenv("ROUTER_MODEL", "").strip() or os.getenv("OPENAI_MODEL", "").strip() or "gpt-4o-mini"),
        openai_max_tokens=_int("OPENAI_MAX_TOKENS", 6000),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "").strip() or "claude-opus-4-8",
        database_url=os.getenv("DATABASE_URL", "").strip() or None,
        max_repairs=_int("A2UI_MAX_REPAIRS", 2),
        catalog_path=Path(
            os.getenv("LOCAL_CATALOG_PATH", "").strip()
            or REPO_ROOT / "node_modules" / "@shadab5114" / "pds-core" / "catalog.json"
        ),
        templates_dir=Path(os.getenv("TEMPLATES_DIR", "").strip() or REPO_ROOT / "templates"),
        data_dir=(data_dir := Path(os.getenv("DATA_DIR", "").strip() or REPO_ROOT / "data")),
        # Declared data providers (app/data/declared.py): one JSON file per provider.
        providers_dir=Path(os.getenv("PROVIDERS_DIR", "").strip() or data_dir / "providers"),
        personas_path=SERVER_DIR / "config" / "personas.json",
        guidelines_dir=Path(os.getenv("GUIDELINES_DIR", "").strip() or REPO_ROOT / "guidelines"),
        rag_url=os.getenv("RAG_URL", "").strip() or None,
        mcp_url=os.getenv("MCP_URL", "").strip() or None,
        mcp_server_script=Path(p) if (p := os.getenv("MCP_SERVER_SCRIPT", "").strip()) else None,
        # gpt-5 / o-series only: "low" keeps turns fast and leaves the output cap for the answer.
        reasoning_effort=(None if (e := os.getenv("OPENAI_REASONING_EFFORT", "low").strip().lower()) in ("", "default") else e),
        guideline_judge=os.getenv("GUIDELINE_JUDGE", "on").strip().lower() not in ("off", "0", "false", "no"),
    )


settings = load_settings()
