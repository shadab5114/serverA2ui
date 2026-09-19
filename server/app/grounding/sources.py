"""Guideline sources for grounding: local markdown now, RAG later, one interface.

Every grounding tool returns {answer, sources} (the P7 contract): `sources` are
citable records (id, title, text, origin), which is what the design brief, the
guideline gate and the trace panel quote.

  LocalGuidelines  sections of the markdown files in GUIDELINES_DIR, each headed
                   "## <ID> · <Title>" (hard-rules.md, guidelines.md). Keyword
                   retrieval: small and deterministic, fine for a handful of rules.
  RagSource        the design-system RAG service (open decision D2). While
                   RAG_URL is unset the call is BYPASSED: it returns no sources
                   and says so. Adapt `_parse` to the real response shape.
  Guidelines       queries all sources and merges their results.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, Protocol

import httpx

from ..config import settings

_SECTION = re.compile(r"^## (?P<id>[A-Z]+-\d+) · (?P<title>.+)$", re.MULTILINE)
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "the a an and or of to for in on with is are be it this that as at by from not no you your me my i "
    "show make build give want need can what which how".split()
)


@dataclass(frozen=True)
class Source:
    id: str  # e.g. "DS-101", or the RAG document id
    title: str
    text: str
    origin: str  # "guidelines/hard-rules.md", "rag", ...

    @property
    def kind(self) -> str:
        """"hard" (DS-1xx), "soft" (DS-2xx), "pattern" (PAT-xxx) or "other"."""
        if self.id.startswith("PAT-"):
            return "pattern"
        if re.fullmatch(r"DS-1\d\d", self.id):
            return "hard"
        if re.fullmatch(r"DS-\d+", self.id):
            return "soft"
        return "other"

    def cite(self) -> str:
        return f"[{self.id} · {self.title}]"


@dataclass
class GroundingResult:
    answer: str
    sources: list[Source] = field(default_factory=list)
    note: str = ""  # e.g. "bypassed: RAG_URL is not set"

    def as_json(self) -> dict[str, Any]:
        return {"answer": self.answer, "sources": [asdict(s) for s in self.sources], "note": self.note}


class GuidelineSource(Protocol):
    name: str

    async def search(self, query: str, k: int = 5) -> GroundingResult: ...


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in _STOP}


@cache
def _parse_markdown(path: Path, mtime: float) -> tuple[Source, ...]:
    raw = path.read_text(encoding="utf-8")
    matches = list(_SECTION.finditer(raw))
    out = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        body = raw[m.end():end].strip()
        out.append(Source(m["id"], m["title"].strip(), body, f"guidelines/{path.name}"))
    return tuple(out)


class LocalGuidelines:
    name = "guidelines.local"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or settings.guidelines_dir

    def all(self) -> list[Source]:
        if not self.root.is_dir():
            return []
        out: list[Source] = []
        for path in sorted(self.root.glob("*.md")):
            out.extend(_parse_markdown(path, path.stat().st_mtime))
        return out

    def get(self, rule_id: str) -> Source | None:
        return next((s for s in self.all() if s.id == rule_id), None)

    async def search(self, query: str, k: int = 5) -> GroundingResult:
        q = _tokens(query)
        scored = []
        for s in self.all():
            title, text = _tokens(s.title), _tokens(s.text)
            score = 3 * len(q & title) + len(q & text) + (5 if s.id.lower() in query.lower() else 0)
            if score:
                scored.append((score, s))
        scored.sort(key=lambda t: (-t[0], t[1].id))
        hits = [s for _, s in scored[:k]]
        return GroundingResult("\n\n".join(f"{s.cite()} {s.text}" for s in hits), hits)


class RagSource:
    """The design-system RAG service. Bypassed until RAG_URL is set (open decision D2)."""

    name = "guidelines.rag"

    def __init__(self, url: str | None = None, timeout: float = 10.0) -> None:
        self.url = url if url is not None else settings.rag_url
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    async def search(self, query: str, k: int = 5) -> GroundingResult:
        if not self.enabled:
            return GroundingResult("", [], note="bypassed: RAG_URL is not set")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # ASSUMED request/response shape until D2 is answered; adapt here and in _parse.
            resp = await client.post(self.url, json={"query": query, "top_k": k})
            resp.raise_for_status()
            return self._parse(resp.json())

    @staticmethod
    def _parse(body: dict[str, Any]) -> GroundingResult:
        sources = [
            Source(
                id=str(s.get("id") or s.get("uri") or f"rag-{i}"),
                title=str(s.get("title") or ""),
                text=str(s.get("text") or s.get("excerpt") or ""),
                origin=str(s.get("uri") or "rag"),
            )
            for i, s in enumerate(body.get("sources") or [])
        ]
        return GroundingResult(str(body.get("answer") or ""), sources)


class Guidelines:
    """All guideline sources behind one search(). Local markdown first; RAG adds to it when enabled."""

    name = "guidelines"

    def __init__(self, sources: list[GuidelineSource] | None = None) -> None:
        self.sources: list[GuidelineSource] = sources if sources is not None else [LocalGuidelines(), RagSource()]

    async def search(self, query: str, k: int = 5) -> GroundingResult:
        answers, merged, notes, seen = [], [], [], set()
        for src in self.sources:
            try:
                res = await src.search(query, k)
            except Exception as err:  # noqa: BLE001 — one source failing mustn't block grounding
                notes.append(f"{src.name}: failed ({err})")
                continue
            if res.note:
                notes.append(f"{src.name}: {res.note}")
            if res.answer:
                answers.append(res.answer)
            for s in res.sources:
                if s.id not in seen:
                    seen.add(s.id)
                    merged.append(s)
        return GroundingResult("\n\n".join(answers), merged, "; ".join(notes))
