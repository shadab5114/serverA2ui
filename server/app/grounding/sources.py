"""Guideline sources for grounding: local markdown now, RAG later, one interface.

Every grounding tool returns {answer, sources} (the P7 contract): `sources` are
citable records (id, title, text, origin), which is what the design brief, the
guideline gate and the trace panel quote.

  LocalGuidelines  sections of the markdown files in GUIDELINES_DIR, each headed
                   "## <ID> · <Title>" (hard-rules.md, guidelines.md). Keyword
                   retrieval: small and deterministic, fine for a handful of rules.
  RagSource        the design-system RAG service: POST RAG_URL {query,
                   collection_name} -> {answer, citations} (decision D2). While
                   RAG_URL is unset the call is BYPASSED: it returns no sources
                   and says so.
  Guidelines       queries all sources and merges their results.

Both are asked on every grounded turn — GENERATE, and equally ADAPT/REFINE, where
the query is the change the user asked for (graph/explore.py `_ground`).
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


# GENUI-PORTING-PLAN.md S5 names the answer source; keep the id stable across both backends.
RAG_ANSWER_ID = "RAG-ANSWER"
RAG_ANSWER_TITLE = "Guidance for this request"
_CITE_TEXT = ("text", "snippet", "content", "excerpt", "chunk", "passage", "quote")
_CITE_REF = ("source", "uri", "url", "document", "file", "path", "filename", "link")
_CITE_TITLE = ("title", "heading", "section", "name", "label")
_CITE_ID = ("id", "doc_id", "document_id", "chunk_id", "ref")
_RULE_ID = re.compile(r"[A-Z]{2,}-\d+")


def _first(cite: dict[str, Any], keys: tuple[str, ...]) -> str:
    """The first of `keys` the citation actually has, as a stripped string."""
    for key in keys:
        value = cite.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool) and str(value).strip():
            return str(value).strip()
    return ""


def _answer_text(body: dict[str, Any]) -> str:
    """The service's answer: "answer", or "answers" as a string or a list of strings."""
    raw = body.get("answer") or body.get("answers")
    if isinstance(raw, list):
        return "\n\n".join(str(a).strip() for a in raw if str(a).strip())
    return str(raw or "").strip()


def _label(ref: str) -> str:
    """A readable title from a document reference: "docs/buttons-and-links.md" -> "buttons and links"."""
    stem = re.split(r"[\\/]", ref.rstrip("/\\"))[-1]
    return re.sub(r"[-_]+", " ", re.sub(r"\.\w{1,5}$", "", stem)).strip()


class RagSource:
    """The design-system RAG service (decision D2, answered 2026-09-25).

        POST <RAG_URL>   {"query": ..., "collection_name": ...}
        200              {"answer": "...", "citations": [...]}

    The `answer` is guidance written for this query, so it becomes a citable source of
    its own (id "RAG-ANSWER") alongside the citations it was built from: it then reaches the
    design brief, the ADAPT/REFINE prompts, the variant cards and the trace panel
    through the same `sources` list as the local markdown, with no second prompt path.

    Citation shapes differ between RAG servers, so `_citation` reads the usual key
    names, tolerates plain strings, and falls back to "RAG-<n>" ids; a citation that
    names a rule ("DS-101") keeps that id, which merges it with the local copy of the
    rule (local text wins, since `Guidelines` queries it first). Bypassed while RAG_URL
    is unset. The endpoint has no top-k param, so `k` clips the citations here.
    """

    name = "guidelines.rag"

    def __init__(
        self,
        url: str | None = None,
        collection: str | None = None,
        timeout: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = url if url is not None else settings.rag_url
        self.collection = collection if collection is not None else settings.rag_collection
        self.timeout = settings.rag_timeout if timeout is None else timeout
        self.transport = transport  # tests inject an httpx.MockTransport

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    @property
    def origin(self) -> str:
        return f"rag/{self.collection}" if self.collection else "rag"

    async def search(self, query: str, k: int = 5) -> GroundingResult:
        if not self.enabled:
            return GroundingResult("", [], note="bypassed: RAG_URL is not set")
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            resp = await client.post(self.url, json={"query": query, "collection_name": self.collection})
            resp.raise_for_status()
            body = resp.json()
        if not isinstance(body, dict):
            return GroundingResult("", [], note=f"unexpected response: {type(body).__name__}, expected an object")
        return self._parse(body, origin=self.origin, k=k)

    @classmethod
    def _parse(cls, body: dict[str, Any], *, origin: str = "rag", k: int = 5) -> GroundingResult:
        answer = _answer_text(body)
        raw = body.get("citations")
        if isinstance(raw, (str, dict)):  # a single citation, unwrapped
            raw = [raw]
        sources = [cls._citation(i, c, origin) for i, c in enumerate(raw or [], 1) if c][:k]
        if answer:
            sources.insert(0, Source(RAG_ANSWER_ID, RAG_ANSWER_TITLE, answer, origin))
        return GroundingResult(answer, sources, "" if sources else "no answer and no citations")

    @classmethod
    def _citation(cls, i: int, cite: Any, origin: str) -> Source:
        if not isinstance(cite, dict):  # citations as bare document refs
            ref = str(cite).strip()
            return Source(cls._cite_id(ref, i), _label(ref) or f"citation {i}", "", ref or origin)
        ref = _first(cite, _CITE_REF)
        title = _first(cite, _CITE_TITLE) or _label(ref) or f"citation {i}"
        page = _first(cite, ("page", "page_number"))
        return Source(
            id=cls._cite_id(f"{_first(cite, _CITE_ID)} {title} {ref}", i),
            title=f"{title} p.{page}" if page else title,
            text=_first(cite, _CITE_TEXT),
            origin=ref or origin,
        )

    @staticmethod
    def _cite_id(hint: str, i: int) -> str:
        """A citation that names a rule ("DS-101 · Primary buttons", "rules/DS-101.md") keeps the rule's id."""
        found = _RULE_ID.search(hint)
        return found.group(0) if found else f"RAG-{i}"


class Guidelines:
    """All guideline sources behind one search(). Local markdown first; RAG adds to it when enabled."""

    name = "guidelines"

    def __init__(self, sources: list[GuidelineSource] | None = None) -> None:
        self.sources: list[GuidelineSource] = sources if sources is not None else [LocalGuidelines(), RagSource()]

    @property
    def targets(self) -> list[str]:
        """Where a search goes, for the trace panel: each source, and the RAG endpoint it will call."""
        out = []
        for src in self.sources:
            where = f" {src.url} ({src.collection})" if isinstance(src, RagSource) and src.enabled else ""
            out.append(f"{src.name}{where}")
        return out

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
