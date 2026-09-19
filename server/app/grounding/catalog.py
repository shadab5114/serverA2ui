"""Load the design-system catalog once (reference: src/localCatalog.js).

Single source of truth: the catalog.json that ships inside @shadab5114/pds-core
(root `npm install`, needs NODE_AUTH_TOKEN for GitHub Packages). Override with
LOCAL_CATALOG_PATH. Shape: {catalogId, components, defs, names}.
"""

from __future__ import annotations

import copy
import json
from functools import cache
from pathlib import Path
from typing import Any

from ..config import settings
from .layout import merge_basic_layout


class CatalogError(RuntimeError):
    pass


@cache
def load_catalog(path: Path | None = None) -> dict[str, Any]:
    """The raw pds catalog (no layout components). Cached; treat as read-only."""
    path = path or settings.catalog_path
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as err:
        raise CatalogError(
            f"Failed to read the component catalog at {path}: {err}. "
            "Is @shadab5114/pds-core installed? Run `npm install` at the repo root "
            "(needs NODE_AUTH_TOKEN, see .npmrc), or set LOCAL_CATALOG_PATH."
        ) from err
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as err:
        raise CatalogError(f"Catalog at {path} is not valid JSON: {err}") from err

    components = doc.get("components") or {}
    if not components:
        raise CatalogError(f"Catalog at {path} has no components.")
    return {
        "catalogId": doc.get("catalogId") or doc.get("$id") or "",
        "components": components,
        "defs": doc.get("$defs") or {},
        "names": list(components),
    }


@cache
def generation_catalog() -> dict[str, Any]:
    """The catalog the generator sees: pds components + borrowed layout components.

    Built on a copy so load_catalog() stays the pure pds catalog the gate validates against.
    """
    return merge_basic_layout(copy.deepcopy(load_catalog()))
