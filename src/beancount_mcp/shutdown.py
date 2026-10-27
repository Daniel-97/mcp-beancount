"""Graceful shutdown coordination for active MCP tool calls."""

from __future__ import annotations

import signal
from typing import Any

from beancount_mcp.logging import log_event


class ShutdownController:
    """Defer the first shutdown signal until the current tool call finishes."""

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self.active_calls = 0
        self.shutdown_requested = False
        self.last_signal = "SIGINT"

    def handle_signal(self, signum: int, frame: Any) -> None:
        try:
            name = signal.Signals(signum).name
        except ValueError:
            name = str(signum)
        self.last_signal = name

        if self.active_calls > 0 and not self.shutdown_requested:
            self.shutdown_requested = True
            log_event(
                f"shutdown: {name} received; finishing current tool call",
                verbose=self.verbose,
            )
            return

        # Idle shutdown, or a second signal while a call is still running.
        raise KeyboardInterrupt(name)


class GracefulShutdownMiddleware:
    """Track active tool calls and stop after the current call completes."""

    def __init__(self, controller: ShutdownController) -> None:
        self._controller = controller

    async def __call__(self, ctx: Any, call_next: Any) -> Any:
        if getattr(ctx, "method", None) != "tools/call":
            return await call_next(ctx)

        self._controller.active_calls += 1
        try:
            return await call_next(ctx)
        finally:
            self._controller.active_calls -= 1
            if self._controller.shutdown_requested:
                self._controller.shutdown_requested = False
                raise KeyboardInterrupt(self._controller.last_signal)
