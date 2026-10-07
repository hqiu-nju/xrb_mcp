import json
from types import SimpleNamespace

import httpx
import pytest
from mcp.types import CallToolResult, TextContent, Tool

from xrb_mcp.agents.ollama import ALLOWED_TOOLS, check_model, local_url, research


class ToolSession:
    def __init__(self):
        self.calls = []

    async def list_tools(self):
        return SimpleNamespace(
            tools=[
                Tool(
                    name=name,
                    description="Fixture",
                    inputSchema={
                        "type": "object",
                        "properties": {"source": {"type": "string"}},
                    },
                )
                for name in [*sorted(ALLOWED_TOOLS), "write_database"]
            ]
        )

    async def call_tool(self, name, arguments, **kwargs):
        self.calls.append((name, arguments))
        if arguments.get("source") == "missing":
            return CallToolResult(
                isError=True, content=[TextContent(type="text", text="Unknown source")]
            )
        return CallToolResult(
            content=[],
            structuredContent={
                "citation": {"doi": "test-only-doi", "page": 2, "provenance_id": "test-id"}
            },
        )


def assistant(calls=None, content="", **extra):
    return {
        "message": {
            "role": "assistant",
            "content": content,
            "thinking": "test reasoning",
            "tool_calls": calls or [],
        },
        **extra,
    }


def call(name, arguments):
    return {"function": {"name": name, "arguments": arguments}}


async def test_multiple_tools_errors_and_citations_round_trip():
    session = ToolSession()
    requests = []

    def handler(request):
        data = json.loads(request.content)
        requests.append(data)
        assert data["stream"] is False
        if len(requests) == 1:
            assert {tool["function"]["name"] for tool in data["tools"]} == ALLOWED_TOOLS
            assert data["tools"][0]["function"]["parameters"]["type"] == "object"
            return httpx.Response(
                200,
                json=assistant(
                    [
                        call("get_source", {"source": "missing"}),
                        call("write_database", {}),
                        call("get_source", "invalid arguments"),
                        call("search_literature", {"query": "radio"}),
                    ]
                ),
            )
        history = data["messages"]
        assert history[2]["thinking"] == "test reasoning"
        results = [json.loads(item["content"]) for item in history if item["role"] == "tool"]
        assert [item["isError"] for item in results] == [True, True, True, False]
        assert results[-1]["data"]["citation"]["provenance_id"] == "test-id"
        assert data["tools"] == []  # final synthesis after one tool round
        return httpx.Response(200, json=assistant(content="Evidence at PDF page 2."))

    async with httpx.AsyncClient(
        base_url="http://localhost:11434", transport=httpx.MockTransport(handler)
    ) as http:
        answer = await research(session, http, "radio?", model="fixture", max_rounds=1)
    assert answer == "Evidence at PDF page 2."
    assert session.calls == [
        ("get_source", {"source": "missing"}),
        ("search_literature", {"query": "radio"}),
    ]


@pytest.mark.parametrize(
    "reply,match",
    [
        (assistant([call("get_source", {})] * 25), "limit"),
        (assistant(content="partial", done_reason="length"), "token limit"),
        (assistant(), "no answer"),
    ],
)
async def test_limits_and_incomplete_output(reply, match):
    session = ToolSession()
    async with httpx.AsyncClient(
        base_url="http://localhost:11434",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=reply)),
    ) as http:
        with pytest.raises(RuntimeError, match=match):
            await research(session, http, "question", model="fixture")
    assert session.calls == []


async def test_model_cannot_continue_tools_after_final_round():
    session = ToolSession()
    async with httpx.AsyncClient(
        base_url="http://localhost:11434",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=assistant([call("get_source", {})]))
        ),
    ) as http:
        with pytest.raises(RuntimeError, match="limit"):
            await research(session, http, "question", model="fixture", max_rounds=1)
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "info,status,error",
    [
        ({"capabilities": ["completion", "tools"]}, 200, None),
        ({"capabilities": ["completion"]}, 200, "tool calling"),
        ({"capabilities": ["tools"], "remote_host": "https://ollama.com"}, 200, "cloud"),
        ({}, 404, "not installed"),
    ],
)
async def test_model_preflight(info, status, error):
    def handler(request):
        assert request.url.path == "/api/show"
        assert json.loads(request.content) == {"model": "fixture"}
        return httpx.Response(status, json=info)

    async with httpx.AsyncClient(
        base_url="http://localhost:11434", transport=httpx.MockTransport(handler)
    ) as http:
        if error:
            with pytest.raises(RuntimeError, match=error):
                await check_model(http, "fixture")
        else:
            await check_model(http, "fixture")


@pytest.mark.parametrize(
    "host",
    [
        "https://ollama.com",
        "http://192.168.1.2:11434",
        "http://localhost.evil.test",
        "http://user:secret@localhost",
        "http://localhost/api",
        "http://localhost?token=secret",
    ],
)
def test_reject_nonlocal_endpoints(host):
    with pytest.raises(ValueError, match="loopback"):
        local_url(host)


@pytest.mark.parametrize(
    "host",
    [
        "http://127.0.0.1:11434",
        "http://localhost:11434/",
        "http://[::1]:11434",
    ],
)
def test_accept_loopback_endpoints(host):
    assert local_url(host) == host.rstrip("/")
