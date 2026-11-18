"""Exercise the standalone chat bridge without a real provider or API key."""

from __future__ import annotations

import asyncio
import io
import json
import runpy
import urllib.error
from email.message import Message
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from beancount_mcp.config import build_config
from beancount_mcp.server import create_server


@pytest.fixture
def script() -> dict[str, Any]:
    return runpy.run_path(str(Path(__file__).parents[2] / "scripts/chat.py"))


def test_provider_maps_schemas_and_sends_credentials_only_to_llm(script: dict[str, Any]) -> None:
    provider = script["Provider"](
        "http://example.test/v1/chat/completions", "test-key", "test-model"
    )
    requests = []

    class Opener:
        def open(self, request: Any, timeout: float) -> io.BytesIO:
            requests.append(request)
            return io.BytesIO(b'{"choices":[{"message":{"role":"assistant","content":"ok"}}]}')

    provider.opener = Opener()
    from mcp.types import Tool

    tool = Tool(name="ledger_info", description="Inspect ledger", input_schema={"type": "object"})
    message = asyncio.run(provider.complete([{"role": "user", "content": "hello"}], [tool]))
    assert message["content"] == "ok"
    request = requests[0]
    assert request.full_url == "http://example.test/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer test-key"
    payload = json.loads(request.data)
    assert payload["model"] == "test-model"
    assert payload["tools"][0]["function"]["parameters"] == {"type": "object"}
    assert "test-key" not in request.data.decode()


def test_multiple_tools_complete_full_roundtrip_against_real_mcp(
    script: dict[str, Any], copy_fixture: Any
) -> None:
    ledger = copy_fixture("minimal")
    output: list[str] = []

    class Provider:
        async def complete(self, messages: list[dict[str, Any]], tools: Any) -> dict[str, Any]:
            if messages[-1]["role"] == "user":
                assert "delete_transaction" not in {tool.name for tool in tools}
                return {
                    "content": None,
                    "reasoning_content": "provider continuation state",
                    "tool_calls": [
                        {
                            "id": "a",
                            "type": "function",
                            "function": {"name": "ledger_info", "arguments": "{}"},
                        },
                        {
                            "id": "b",
                            "type": "function",
                            "function": {"name": "validate", "arguments": "{}"},
                        },
                    ],
                }
            assert messages[-3]["reasoning_content"] == "provider continuation state"
            assert [m["tool_call_id"] for m in messages[-2:]] == ["a", "b"]
            info = json.loads(messages[-2]["content"])
            assert info["ok"] and info["accounts"]
            assert json.loads(messages[-1]["content"])["valid"] is True
            return {"content": "Ledger valido."}

    async def exercise() -> None:
        async with Client(create_server(build_config(str(ledger.main))), cache=None) as client:
            tools = await script["list_tools"](client)
            chat = script["Chat"](client, Provider(), tools, output=output.append)
            await chat.turn("Controlla il ledger")
            assert len(chat.messages) == 6

    asyncio.run(exercise())
    assert any("ledger_info" in line for line in output)
    assert any("Ledger valido." in line for line in output)


def test_writes_need_explicit_mode_and_direct_calls_do_not_enter_model_history(
    script: dict[str, Any], copy_fixture: Any
) -> None:
    ledger = copy_fixture("minimal")
    before = ledger.inbox.read_bytes()
    text = '2026-02-01 * "Test"\n  Assets:Cash -2 EUR\n  Expenses:Food 2 EUR\n'

    async def exercise() -> None:
        async with Client(create_server(build_config(str(ledger.main))), cache=None) as client:
            tools = await script["list_tools"](client)
            chat = script["Chat"](client, None, tools, output=lambda _: None)
            denied = json.loads(await chat.call("add_transactions", {"text": text}))
            assert denied["error"]["code"] == "WRITES_DISABLED"
            assert ledger.inbox.read_bytes() == before
            await chat.command("/writes on")
            assert "add_transactions" in {t.name for t in chat.available()}
            assert await chat.command("/call add_transactions " + json.dumps({"text": text}))
            assert len(chat.messages) == 1
            await chat.command("/writes off")
            assert "add_transactions" not in {t.name for t in chat.available()}
            assert not await chat.command("/quit")

    asyncio.run(exercise())
    assert text.strip() in ledger.inbox.read_text()


def test_invalid_arguments_and_unknown_tools_are_sent_back_to_model(script: dict[str, Any]) -> None:
    class Provider:
        async def complete(self, messages: Any, tools: Any) -> dict[str, Any]:
            if messages[-1]["role"] == "user":
                return {
                    "tool_calls": [
                        {"id": "a", "function": {"name": "bogus", "arguments": "{"}},
                        {"id": "b", "function": {"name": "bogus", "arguments": "{}"}},
                    ]
                }
            assert json.loads(messages[-2]["content"])["error"]["code"] == "INVALID_ARGUMENTS"
            assert json.loads(messages[-1]["content"])["error"]["code"] == "UNKNOWN_TOOL"
            return {"content": "Cannot call that tool."}

    chat = script["Chat"](None, Provider(), [], output=lambda _: None)
    asyncio.run(chat.turn("hello"))


def test_interrupted_tool_is_never_retried(script: dict[str, Any]) -> None:
    from mcp.types import Tool

    calls = []

    class BrokenMCP:
        async def call_tool(self, *args: Any) -> None:
            calls.append(args)
            raise TimeoutError()

    chat = script["Chat"](
        BrokenMCP(),
        None,
        [Tool(name="add_transactions", input_schema={})],
        allow_writes=True,
        output=lambda _: None,
    )
    with pytest.raises(script["PlaygroundError"], match="incerto"):
        asyncio.run(chat.call("add_transactions", {"text": "test"}))
    assert len(calls) == 1


def test_provider_errors_redact_keys(script: dict[str, Any]) -> None:
    provider = script["Provider"]("https://example.test/v1", "test-secret", "model")

    class Opener:
        def open(self, request: Any, timeout: float) -> None:
            raise urllib.error.HTTPError(
                request.full_url, 401, "error", Message(), io.BytesIO(b'{"error":"test-secret"}')
            )

    provider.opener = Opener()
    with pytest.raises(script["PlaygroundError"]) as error:
        provider.request("/models")
    assert "test-secret" not in str(error.value)
    assert "[API KEY]" in str(error.value)
