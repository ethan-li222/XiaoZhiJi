import asyncio
import json
import os
import shutil
from pathlib import Path

from .config import PROJECT_ROOT
from .models import Paper


class BrowserPaperSearch:
    def __init__(self, settings):
        self.settings = settings

    async def search(
        self, query, limit=20, site="both", sort="relevance", year_from=None, year_to=None
    ):
        node = shutil.which("node")
        playwright = PROJECT_ROOT / "ppt/node_modules/playwright"
        if not node or not playwright.exists():
            raise ValueError("浏览器检索需要 Node.js 与已安装的 Playwright")
        payload = dict(
            query=query,
            limit=limit,
            site=site,
            sort=sort,
            year_from=year_from,
            year_to=year_to,
            chrome_path=self.settings.chrome_path,
            playwright_path=str(playwright),
        )
        process = await asyncio.create_subprocess_exec(
            node,
            str(Path(__file__).with_name("browser_search.cjs")),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(json.dumps(payload).encode()),
                timeout=max(1, min(125, self.settings.tool_timeout - 5)),
            )
        except BaseException as exc:
            if process.returncode is None:
                if os.name == "nt":
                    cleanup = await asyncio.create_subprocess_exec(
                        "taskkill",
                        "/PID",
                        str(process.pid),
                        "/T",
                        "/F",
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await cleanup.wait()
                else:
                    process.kill()
                await process.wait()
            if isinstance(exc, TimeoutError):
                raise ValueError("本地 Chrome 检索超时，请缩小数量或只选择一个来源") from None
            raise
        if process.returncode:
            raise ValueError(
                "本地 Chrome 检索失败：" + stderr.decode("utf-8", errors="replace")[:500]
            )
        result = json.loads(stdout)
        result["papers"] = [Paper.model_validate(p).model_dump() for p in result["papers"]]
        return result
