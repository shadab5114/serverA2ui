"""Curated template library (static generative UI).

A template is A2UI a person wrote: `templates/<id>/surface.json` (messages with
data bindings, surface id "main", no data) plus `manifest.json` (what it's for,
who may use it, which data provider fills it). Both personas share one library.

TemplateStore is the seam for a future object store (open decision D4);
FileTemplateStore reads TEMPLATES_DIR on every call, so designers' edits show
up without a restart.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


class TemplateError(ValueError):
    pass


@dataclass(frozen=True)
class Manifest:
    id: str
    version: int
    title: str
    intent: str
    examples: list[str]
    personas: list[str]
    provider: str
    caption: str
    suggested_next: list[str]
    events: dict[str, str] = field(default_factory=dict)  # event name -> what it means (P6)

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> Manifest:
        try:
            return cls(
                id=raw["id"],
                version=int(raw["version"]),
                title=raw["title"],
                intent=raw["intent"],
                examples=list(raw.get("examples", [])),
                personas=list(raw["personas"]),
                provider=raw["data"]["provider"],
                caption=raw.get("caption") or "Here you go.",
                suggested_next=list(raw.get("suggestedNext", [])),
                events=dict(raw.get("events", {})),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise TemplateError(f"bad manifest {raw.get('id', '?')!r}: {err}") from err


@dataclass(frozen=True)
class Template:
    manifest: Manifest
    surface: dict[str, Any]  # {"a2ui": [...]}


class TemplateStore(Protocol):
    def manifests(self) -> list[Manifest]: ...
    def get(self, template_id: str) -> Template: ...


class FileTemplateStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def manifests(self) -> list[Manifest]:
        if not self.root.is_dir():
            return []
        out = []
        for path in sorted(self.root.glob("*/manifest.json")):
            m = Manifest.from_json(json.loads(path.read_text(encoding="utf-8")))
            if m.id != path.parent.name:
                raise TemplateError(f"manifest id {m.id!r} doesn't match its folder {path.parent.name!r}")
            out.append(m)
        return out

    def get(self, template_id: str) -> Template:
        folder = self.root / template_id
        if not (folder / "manifest.json").is_file():
            raise TemplateError(f"no template {template_id!r} in {self.root}")
        manifest = Manifest.from_json(json.loads((folder / "manifest.json").read_text(encoding="utf-8")))
        surface = json.loads((folder / "surface.json").read_text(encoding="utf-8"))
        return Template(manifest, surface)
