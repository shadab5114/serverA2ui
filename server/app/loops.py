"""Event-loop factory for uvicorn.

psycopg's async mode can't run on the Proactor loop (the Windows default). Since
uvicorn 0.36 the loop comes from a factory, not the asyncio policy, so setting
WindowsSelectorEventLoopPolicy alone would be ignored. run.py points uvicorn's
`loop=` at this function; a custom import string is used as the factory itself.
"""

from __future__ import annotations

import asyncio


def selector_loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop()
