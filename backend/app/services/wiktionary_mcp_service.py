import os
import json
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


WIKTIONARY_MCP_URL = os.getenv(
    "WIKTIONARY_MCP_URL",
    "http://192.168.0.22:8010/mcp"
)

MCP_TIMEOUT_SECONDS = float(
    os.getenv("MCP_TIMEOUT_SECONDS", "8")
)


async def _call_wiktionary_mcp(term: str) -> dict:
    async with streamablehttp_client(WIKTIONARY_MCP_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool(
                "wiktionary_parse_page",
                arguments={"term": term}
            )

            if not result.content:
                return {
                    "found": False,
                    "term": term,
                    "message": "Empty MCP response"
                }

            raw_text = result.content[0].text

            try:
                return json.loads(raw_text)

            except json.JSONDecodeError:
                return {
                    "found": False,
                    "term": term,
                    "message": "Invalid JSON from MCP",
                    "raw_text": raw_text[:500]
                }


async def lookup_wiktionary(term: str) -> dict:
    clean_term = term.strip()

    if not clean_term:
        return {
            "found": False,
            "term": term,
            "message": "Empty term"
        }

    try:
        return await asyncio.wait_for(
            _call_wiktionary_mcp(clean_term),
            timeout=MCP_TIMEOUT_SECONDS
        )

    except asyncio.TimeoutError:
        return {
            "found": False,
            "term": clean_term,
            "message": f"MCP timeout after {MCP_TIMEOUT_SECONDS} seconds"
        }

    except Exception as e:
        return {
            "found": False,
            "term": clean_term,
            "message": str(e)
        }