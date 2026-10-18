import importlib
import logging
import os
import sys
from functools import lru_cache

from mcp.server.fastmcp import FastMCP

from .config import get_settings
from .tools import Tools

mcp = FastMCP("小知己")


@lru_cache
def tools():
    return Tools(get_settings())


@mcp.tool()
async def papers(action: str, params: dict) -> dict:
    """Explore papers. action: search/related/map/download; map uses citation structure."""
    if action not in {"search", "related", "download", "map"}:
        raise ValueError("action 只支持 search/related/download/map")
    return await tools().call("papers." + action, params)


@mcp.tool()
async def documents(action: str, params: dict) -> dict:
    """Import/open/delete an article, or retrieve reading context. action: import/open/delete/ask."""
    mapping = {
        "import": "documents.import",
        "open": "documents.open",
        "delete": "documents.delete",
        "ask": "reading.ask",
    }
    if action not in mapping:
        raise ValueError("action 只支持 import/open/delete/ask")
    return await tools().call(mapping[action], params)


@mcp.tool()
async def knowledge(action: str, params: dict) -> dict:
    """Curate reading memory. action: save/search/update/review/export/delete."""
    if action not in {"save", "search", "delete", "update", "review", "export"}:
        raise ValueError("action 只支持 save/search/update/review/export/delete")
    return await tools().call("knowledge." + action, params)


@mcp.tool()
async def sources(params: dict) -> dict:
    """Collect dated academic/industry sources for a configured topic and time window."""
    return await tools().call("reports.generate", params)


@mcp.tool()
async def workspace(action: str, params: dict) -> dict:
    """Manage projects/library/annotations/ideas/experiments; stats/weekly/synthesize/coach."""
    return await tools().call("workspace." + action, params)


@mcp.tool()
async def chat(action: str, params: dict) -> dict:
    """Prepare scoped conversation context. action: send. The workflow generates the response."""
    if action != "send":
        raise ValueError("action 只支持 send")
    return await tools().call("chat.send", params)


@mcp.tool()
async def memory(action: str, params: dict) -> dict:
    """Independent personal notes: note.save/note.delete/search/review/export."""
    return await tools().call("memory." + action, params)


@mcp.tool()
async def slides(params: dict) -> dict:
    """Render a structured deck into an editable local PPTX file."""
    return await tools().call("slides.build", params)


def main():
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    # Some source APIs accept keys in query parameters; suppress HTTP URL logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # Windows native BLAS dependencies can block when first imported by a worker
    # while stdio reader threads are active. Import before starting those threads.
    if os.name == "nt" and get_settings().embedding_dir.exists():
        importlib.import_module("sentence_transformers")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
