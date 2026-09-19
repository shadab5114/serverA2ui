"""POLICY: plain code that enforces what each persona may do.

DECIDE (an LLM) proposes; this disposes. Allowed strategies come from
server/config/personas.json, so behavior is predictable and unit-testable.
"""

from __future__ import annotations

import json
from collections.abc import Collection
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import settings

if TYPE_CHECKING:
    from ..templates.store import Manifest
    from .decide import Decision

DEFAULT_PERSONA = "assistant"

# When a proposed strategy isn't allowed (or can't be carried out), try these in order.
# TEXT is always the last resort.
FALLBACKS: dict[str, list[str]] = {
    "ADAPT": ["GENERATE", "TEMPLATE"],  # the gaps need new structure: build fresh rather than show a partial fit
    "REFINE": ["GENERATE"],
    "TEMPLATE": ["GENERATE"],
    "GENERATE": [],
    "TEXT": [],
}


@dataclass(frozen=True)
class Persona:
    name: str
    description: str
    strategies: tuple[str, ...]
    variants: int
    on_guideline_conflict: str
    show_rationale: bool


@cache
def _load_personas(path: Path) -> dict[str, Persona]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        name: Persona(
            name=name,
            description=p.get("description", ""),
            strategies=tuple(p["strategies"]),
            variants=int(p.get("variants", 1)),
            on_guideline_conflict=p.get("onGuidelineConflict", "repair"),
            show_rationale=bool(p.get("showRationale", False)),
        )
        for name, p in raw.items()
    }


def personas() -> dict[str, Persona]:
    return _load_personas(settings.personas_path)


def resolve_persona(name: Any) -> Persona:
    table = personas()
    return table.get(name) if isinstance(name, str) and name in table else table[DEFAULT_PERSONA]


@dataclass
class Plan:
    """The decision after policy: what will actually run."""

    strategy: str
    template_id: str | None
    params: dict[str, str]
    reason: str
    proposed: str
    coverage: str
    gaps: list[str]
    intent: str
    persona: str
    notes: list[str] = field(default_factory=list)
    data_providers: list[str] = field(default_factory=list)  # GENERATE: providers GROUND loads real data from
    target: str | None = None  # REFINE: the on-screen surface to change (P8)
    variants: int = 1  # ADAPT: how many variants to propose (the persona's "variants")

    def label(self) -> str:
        return f"{self.strategy} {self.template_id}" if self.template_id else self.strategy

    def as_meta(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "proposed": self.proposed,
            "templateId": self.template_id,
            "params": self.params,
            "coverage": self.coverage,
            "gaps": self.gaps,
            "reason": self.reason,
            "persona": self.persona,
            "policyNotes": self.notes,
            "dataProviders": self.data_providers,
            "target": self.target,
            "variants": self.variants,
        }


def fill_params_from_selections(plan: Plan, provider_params: list[str], selections: dict[str, Any]) -> None:
    """Provider params DECIDE left out but the user already chose on screen (e.g. planId
    from a Choose click) come from state, not from the model."""
    if plan.strategy not in ("TEMPLATE", "ADAPT"):
        return
    for name in provider_params:
        value = selections.get(name)
        if name not in plan.params and isinstance(value, (str, int, float, bool)) and value != "":
            plan.params[name] = str(value)
            plan.notes.append(f"{name}={value} from the user's selection")


def apply_policy(
    decision: Decision,
    persona: Persona,
    manifests: list[Manifest],
    on_screen: Collection[str] = (),
    latest: str | None = None,
) -> Plan:
    """on_screen: ids of the thread's surfaces (lineage), the only valid REFINE targets.
    latest: the surface shown most recently, which a REFINE without a (valid) target modifies."""
    usable = {m.id: m for m in manifests if persona.name in m.personas}
    notes: list[str] = []
    target = decision.target
    if decision.strategy == "REFINE" and target not in on_screen and latest in on_screen:
        notes.append(f"REFINE target {target!r} isn't on screen → the latest surface, {latest}" if target
                     else f"REFINE without a target → the latest surface, {latest}")
        target = latest

    def blocker(strategy: str) -> str | None:
        """Why this strategy can't run for this persona and decision (None = it can)."""
        if strategy not in persona.strategies and strategy != "TEXT":
            return f"{strategy} isn't allowed for {persona.name}"
        if strategy in ("TEMPLATE", "ADAPT") and decision.templateId not in usable:
            return f"template {decision.templateId!r} isn't available to {persona.name}"
        if strategy == "REFINE" and target not in on_screen:
            return f"REFINE target {target!r} isn't on screen"
        return None

    strategy = decision.strategy
    why = blocker(strategy)
    if why:
        strategy = next((s for s in FALLBACKS.get(strategy, []) if blocker(s) is None), "TEXT")
        notes.append(f"{why} → {strategy}")

    uses_template = strategy in ("TEMPLATE", "ADAPT")
    return Plan(
        strategy=strategy,
        template_id=decision.templateId if uses_template else None,
        params={p.name: p.value for p in decision.params} if uses_template else {},
        reason=decision.reason,
        proposed=decision.strategy,
        coverage=decision.coverage,
        gaps=list(decision.gaps),
        intent=decision.intent,
        persona=persona.name,
        notes=notes,
        # Only known providers, and only for GENERATE (templates name their own provider).
        data_providers=[p for p in decision.dataProviders if p in _known_providers()] if strategy == "GENERATE" else [],
        target=target if strategy == "REFINE" else None,
        variants=persona.variants if strategy == "ADAPT" else 1,
    )


def _known_providers() -> set[str]:
    from ..data.providers import REGISTRY

    return set(REGISTRY)
