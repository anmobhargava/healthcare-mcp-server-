import asyncio
import os
import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, SRC)

from mcp import ClientSession, StdioServerParameters           # noqa: E402
from mcp.client.stdio import stdio_client                       # noqa: E402


def run(coro):
    return asyncio.run(coro)


def over_stdio(fn):
    """Starts the real server as a subprocess, speaks real MCP to it, and hands the live session to `fn`."""
    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "healthmcp", "--demo-data"], env={**os.environ, "PYTHONPATH": SRC})
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                return await fn(s)
    return run(go())
