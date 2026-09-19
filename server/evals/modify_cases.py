"""Modify ("REFINE") accuracy cases on NON-plan screens: the engine must not depend on the plan demo.

Each case is a screen (a valid A2UI doc with its data), a request, and a check run by code on
the result. Used by tests/test_modify_eval.py (real model, `uv run pytest -m eval`).
"""

from __future__ import annotations

from typing import Any


def doc(components: list[dict[str, Any]], data: dict[str, Any]) -> dict[str, Any]:
    return {"a2ui": [
        {"version": "v0.9", "createSurface": {"surfaceId": "main", "catalogId": "x"}},
        {"version": "v0.9", "updateDataModel": {"surfaceId": "main", "path": "/", "value": data}},
        {"version": "v0.9", "updateComponents": {"surfaceId": "main", "components": components}},
    ]}


ORDERS = doc(
    [
        {"id": "root", "component": "Column", "children": ["heading", "order-list"]},
        {"id": "heading", "component": "Text", "kind": "title", "size": "large", "children": "Your orders"},
        {"id": "order-list", "component": "Column", "children": {"path": "/orders", "componentId": "order-card"}},
        {"id": "order-card", "component": "Tilelet", "showBorder": True,
         "title": {"children": {"path": "item"}}, "subtitle": {"children": {"path": "statusLabel"}},
         "eyebrow": {"children": {"path": "id"}}},
    ],
    {"orders": [
        {"id": "A-1001", "item": "Desk lamp", "status": "shipped", "statusLabel": "Shipped, arrives Tue"},
        {"id": "A-1002", "item": "Office chair", "status": "delayed", "statusLabel": "Delayed, new date pending"},
        {"id": "A-1003", "item": "Monitor arm", "status": "delivered", "statusLabel": "Delivered Mon"},
        {"id": "A-1004", "item": "Cable tray", "status": "delayed", "statusLabel": "Delayed, arrives next week"},
    ]},
)

SETTINGS = doc(
    [
        {"id": "root", "component": "Column", "children": ["title", "name-field", "notify-label", "notify-toggle", "save"]},
        {"id": "title", "component": "Text", "kind": "title", "size": "large", "children": "Settings"},
        {"id": "name-field", "component": "InputField", "label": "Display name", "value": {"path": "/form/name"}},
        {"id": "notify-label", "component": "Text", "kind": "body", "size": "medium", "children": "Email notifications"},
        {"id": "notify-toggle", "component": "Toggle", "ariaLabel": "Email notifications", "checked": {"path": "/form/notifications"}},
        {"id": "save", "component": "Button", "children": "Save", "action": {"event": {"name": "save_settings"}}},
    ],
    {"form": {"name": "", "notifications": True}},
)

PRODUCTS = doc(
    [
        {"id": "root", "component": "Column", "children": ["heading", "product-row"]},
        {"id": "heading", "component": "Text", "kind": "title", "size": "large", "children": "New arrivals"},
        {"id": "product-row", "component": "Row", "children": {"path": "/products", "componentId": "product-card"}},
        {"id": "product-card", "component": "Tilelet", "showBorder": True,
         "title": {"children": {"path": "name"}}, "subtitle": {"children": {"path": "priceLabel"}}},
    ],
    {"products": [
        {"id": "p1", "name": "Rain jacket", "priceLabel": "$89"},
        {"id": "p2", "name": "Trail shoes", "priceLabel": "$120"},
        {"id": "p3", "name": "Wool socks", "priceLabel": "$18"},
    ]},
)

DASHBOARD = doc(
    [
        {"id": "root", "component": "Column", "children": ["alert", "uptime", "latency"]},
        {"id": "alert", "component": "Notification", "kind": "information", "inline": True,
         "title": "System status", "children": {"path": "/status/message"}},
        {"id": "uptime", "component": "Text", "kind": "body", "size": "large", "children": {"path": "/stats/uptime"}},
        {"id": "latency", "component": "Text", "kind": "body", "size": "large", "children": {"path": "/stats/latency"}},
    ],
    {"status": {"message": "All systems normal"}, "stats": {"uptime": "99.98% uptime", "latency": "120 ms median"}},
)

SCREENS = {"orders": ORDERS, "settings": SETTINGS, "products": PRODUCTS, "dashboard": DASHBOARD}
