"""Readable, dependency-free flow logging (mirrors src/logger.js).

A clear step-by-step trace of how a request moves through the pipeline, not
machine JSON. Each request gets a short id and per-step timings so concurrent
requests stay legible.
"""

from __future__ import annotations

import itertools
import os
import sys
import time
from contextvars import ContextVar
from datetime import datetime, timezone

_use_color = sys.stdout.isatty() and not os.getenv("NO_COLOR")


def _paint(code: str, s: str) -> str:
    return f"\x1b[{code}m{s}\x1b[0m" if _use_color else s


def dim(s: str) -> str: return _paint("90", s)
def cyan(s: str) -> str: return _paint("36", s)
def green(s: str) -> str: return _paint("32", s)
def yellow(s: str) -> str: return _paint("33", s)
def red(s: str) -> str: return _paint("31", s)
def bold(s: str) -> str: return _paint("1", s)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]


def _base36(n: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while True:
        n, r = divmod(n, 36)
        out = digits[r] + out
        if n == 0:
            return out


_counter = itertools.count(1)


def _emit(line: str, err: bool = False) -> None:
    print(line, file=sys.stderr if err else sys.stdout, flush=True)


class RequestLogger:
    """Per-request logger: start, step, warn, done, fail."""

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.id = _base36(next(_counter)).rjust(3, "0")
        self._t0 = self._last = time.perf_counter()

    def _prefix(self) -> str:
        return f"{dim(_stamp())} {cyan(self.tag)} {dim('#' + self.id)}"

    def _lap(self) -> str:
        now = time.perf_counter()
        d, self._last = (now - self._last) * 1000, now
        return dim(f"+{d:.0f}ms")

    def _total(self) -> str:
        return f"{(time.perf_counter() - self._t0) * 1000:.0f}ms"

    def start(self, msg: str) -> None:
        _emit(f"{self._prefix()} {bold('▶')}  {msg}")

    def step(self, msg: str) -> None:
        _emit(f"{self._prefix()} {dim('│')}  {msg}  {self._lap()}")

    def warn(self, msg: str) -> None:
        _emit(f"{self._prefix()} {yellow('│  ⚠')}  {msg}  {self._lap()}", err=True)

    def done(self, msg: str) -> None:
        _emit(f"{self._prefix()} {green('└▶')} {msg}  {dim('(' + self._total() + ' total)')}")

    def fail(self, msg: str) -> None:
        _emit(f"{self._prefix()} {red('└✗')} {msg}  {dim('(' + self._total() + ' total)')}", err=True)


def request_logger(tag: str) -> RequestLogger:
    return RequestLogger(tag)


# The logger of the request being served. Set by the AG-UI bridge; asyncio copies
# context into the graph's node tasks, so nodes can log into the same trace.
current_log: ContextVar[RequestLogger | None] = ContextVar("current_log", default=None)
