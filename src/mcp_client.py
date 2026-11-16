"""Execute one controller-approved MCP tool call; never retry a write here."""
import asyncio
from datetime import timedelta
import os


def call_create_ticket(arguments, token):
    # Lazy imports keep pure routing and storage unit tests independent of the SDK.
    async def run():
        from mcp import ClientSession
        from mcp.client.sse import sse_client
        async with sse_client(os.environ['MCP_SERVER_URL'],
                              headers={'Authorization': 'Bearer ' + token},
                              timeout=10, sse_read_timeout=35) as streams:
            async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=35)) as session:
                await session.initialize()
                result = await session.call_tool('create-ticket', arguments)
                if result.isError:
                    raise RuntimeError('MCP create-ticket failed')
                return result.model_dump(by_alias=True, exclude_none=True)
    async def bounded():
        async with asyncio.timeout(35):
            return await run()
    return asyncio.run(bounded())
