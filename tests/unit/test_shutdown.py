"""Unit tests for graceful shutdown coordination."""

from __future__ import annotations

import asyncio
import signal
from types import SimpleNamespace

import pytest

from beancount_mcp.shutdown import (
    GracefulShutdownMiddleware,
    ShutdownController,
)


def testShutdownController_shouldDeferFirstSignal_whenToolIsActive() -> None:
    # Given
    controller = ShutdownController()
    controller.active_calls = 1

    # When
    controller.handle_signal(signal.SIGINT, None)

    # Then
    assert controller.shutdown_requested is True
    assert controller.last_signal == "SIGINT"


def testShutdownController_shouldRaiseOnSecondSignal_whenToolIsActive() -> None:
    # Given
    controller = ShutdownController()
    controller.active_calls = 1
    controller.handle_signal(signal.SIGINT, None)

    # When / Then
    with pytest.raises(KeyboardInterrupt):
        controller.handle_signal(signal.SIGINT, None)


def testShutdownController_shouldRaise_whenIdle() -> None:
    # Given
    controller = ShutdownController()

    # When / Then
    with pytest.raises(KeyboardInterrupt):
        controller.handle_signal(signal.SIGTERM, None)


def testMiddleware_shouldRaiseAfterToolCompletes_whenShutdownRequested() -> None:
    # Given
    controller = ShutdownController()
    middleware = GracefulShutdownMiddleware(controller)
    context = SimpleNamespace(method="tools/call")

    async def call_next(_: object) -> dict[str, object]:
        controller.handle_signal(signal.SIGINT, None)
        return {"ok": True}

    # When
    async def run() -> object:
        return await middleware(context, call_next)

    # Then
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(run())
    assert controller.active_calls == 0


def testMiddleware_shouldPassThroughNonToolRequest() -> None:
    # Given
    controller = ShutdownController()
    middleware = GracefulShutdownMiddleware(controller)
    context = SimpleNamespace(method="initialize")

    async def call_next(_: object) -> dict[str, object]:
        return {"ok": True}

    # When
    result = asyncio.run(middleware(context, call_next))

    # Then
    assert result == {"ok": True}
    assert controller.active_calls == 0


def testMiddleware_shouldDecrementActiveCalls_whenToolRaises() -> None:
    # Given
    controller = ShutdownController()
    middleware = GracefulShutdownMiddleware(controller)
    context = SimpleNamespace(method="tools/call")

    async def call_next(_: object) -> dict[str, object]:
        raise ValueError("boom")

    # When / Then
    with pytest.raises(ValueError, match="boom"):
        asyncio.run(middleware(context, call_next))
    assert controller.active_calls == 0
