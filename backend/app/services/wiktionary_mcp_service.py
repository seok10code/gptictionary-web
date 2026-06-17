import os
import json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

WIKTIONARY_MCP_URL = os.getenv(
    "WIKTIONARY_MCP_URL",
    "http://192.168.0.22:8010/mcp"
)

async def lookup_wiktionary(term: str) -> dict:
    async with streamablehttp_client(WIKTIONARY_MCP_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "wiktionary_parse_page",
                arguments={"term": term}
            )

            if not result.content:
                return {"found": False, "term": term}

            return json.loads(result.content[0].text)
