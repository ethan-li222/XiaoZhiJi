import asyncio
import json
import os
import shutil
import sys
from contextlib import asynccontextmanager
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import PROJECT_ROOT


@asynccontextmanager
async def connect(params, timeout=180):
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(
                read, write, read_timeout_seconds=timedelta(seconds=timeout)
            ) as session:
                await session.initialize()
                yield session
    except BaseExceptionGroup as exc:
        leaf = exc
        while isinstance(leaf, BaseExceptionGroup) and len(leaf.exceptions) == 1:
            leaf = leaf.exceptions[0]
        if isinstance(leaf, Exception):
            raise leaf from None
        raise


@asynccontextmanager
async def browser_session(settings):
    node = shutil.which("node")
    script = PROJECT_ROOT / "ppt/node_modules/@playwright/mcp/cli.js"
    if not node or not script.exists():
        raise ValueError("未找到 Playwright MCP；请安装 Node.js 并运行 npm ci --prefix ppt")
    output = settings.data_dir / "browser"
    output.mkdir(parents=True, exist_ok=True)
    args = [
        str(script),
        "--browser",
        "chrome",
        "--isolated",
        "--headless",
        "--output-dir",
        str(output),
    ]
    if settings.chrome_path:
        args.extend(["--executable-path", settings.chrome_path])
    async with connect(
        StdioServerParameters(command=node, args=args, env=dict(os.environ)), settings.tool_timeout
    ) as session:
        yield session


class Gateway:
    def __init__(self, settings, local_tools=None):
        self.settings, self.local_tools = settings, local_tools
        self.session = None

    @asynccontextmanager
    async def open(self):
        if self.local_tools is not None or self.settings.tool_transport == "local":
            if self.local_tools is None:
                from .tools import Tools

                self.local_tools = Tools(self.settings)
            yield self
        else:
            env = dict(os.environ)
            # Explicit settings override env/.env for the subprocess; never log this mapping.
            for name, value in self.settings.model_dump().items():
                if value is None:
                    env["RESEARCH_" + name.upper()] = "null"
                    continue
                if hasattr(value, "get_secret_value"):
                    value = value.get_secret_value()
                if isinstance(value, (dict, list)):
                    value = json.dumps(value)
                env["RESEARCH_" + name.upper()] = (
                    str(value).lower() if isinstance(value, bool) else str(value)
                )
            env["PYTHONIOENCODING"] = "utf-8"
            params = StdioServerParameters(
                command=sys.executable, args=["-m", "research_agent.mcp_server"], env=env
            )
            async with connect(params, self.settings.tool_timeout) as session:
                self.session = session
                try:
                    yield self
                finally:
                    self.session = None

    async def call(self, action, params):
        if self.local_tools:
            return await self.local_tools.call(action, params)
        namespace, operation = action.split(".", 1)
        if namespace == "reading":
            name, args = "documents", {"action": "ask", "params": params}
        elif namespace == "reports":
            name, args = "sources", {"params": params}
        elif namespace == "slides":
            name, args = "slides", {"params": params}
        else:
            name, args = namespace, {"action": operation, "params": params}
        result = await asyncio.wait_for(
            self.session.call_tool(name, args), self.settings.tool_timeout
        )
        if result.isError:
            # MCP tool errors are expected business messages, not configuration dumps.
            detail = " ".join(c.text for c in result.content if hasattr(c, "text"))
            raise ValueError(detail[:1000])
        if result.structuredContent is not None:
            return result.structuredContent
        return json.loads("".join(c.text for c in result.content if hasattr(c, "text")))


async def load_adapter_tools(settings):
    """Configurable LangChain adapters, matching the reference project's loading style.

    Stateful Chrome operations use browser_session instead of stateless get_tools calls.
    """
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient(
        {
            "research": {
                "transport": "stdio",
                "command": sys.executable,
                "args": ["-m", "research_agent.mcp_server"],
                "env": {"RESEARCH_DATA_DIR": str(settings.data_dir)},
            }
        }
    )
    return client, await client.get_tools()
