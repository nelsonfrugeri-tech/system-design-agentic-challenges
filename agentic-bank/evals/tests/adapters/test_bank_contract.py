"""The harness's list of read tools matches what bank-mcp declares read-only."""

import asyncio

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from harness.domain.expected import READ_TOOLS
from tests.conftest import BankServer


async def read_only_tools(url: str) -> set[str]:
    # list_tools is not a tool call, so nothing lands in `calls`.
    async with (
        httpx.AsyncClient(timeout=5) as http,
        streamable_http_client(url, http_client=http) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        listed = await session.list_tools()
    return {
        tool.name
        for tool in listed.tools
        if tool.annotations is not None and tool.annotations.readOnlyHint
    }


def test_read_tools_match_the_bank_annotations(bank_server: BankServer) -> None:
    assert asyncio.run(read_only_tools(bank_server.url)) == READ_TOOLS
