import asyncio
from pathlib import Path

from .config import PROJECT_ROOT
from .models import SlideDeck


def validate_deck(deck):
    ids = {s.id for s in deck.sources}
    for slide in deck.slides:
        if not set(slide.source_ids) <= ids:
            raise ValueError("PPT 包含不存在的来源标识")
        if slide.table and (len({len(r) for r in slide.table}) != 1 or len(slide.table[0]) > 6):
            raise ValueError("表格各行列数应相同，最多六列")
        if slide.chart:
            labels = slide.chart[0].labels
            if not labels or any(
                s.labels != labels or len(s.values) != len(labels) for s in slide.chart
            ):
                raise ValueError("图表标签和数值必须对齐")
    return deck


async def render_deck(deck, output, node="node"):
    deck = validate_deck(SlideDeck.model_validate(deck))
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    data = output.with_suffix(".json")
    data.write_text(deck.model_dump_json(indent=2), encoding="utf-8")
    process = await asyncio.create_subprocess_exec(
        node,
        str(PROJECT_ROOT / "ppt" / "render.cjs"),
        str(data),
        str(output),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 120)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise ValueError("PPT 渲染超时") from None
    if process.returncode:
        raise ValueError("PPT 渲染失败：" + stderr.decode("utf-8", errors="replace")[-1500:])
    return {"pptx": str(output), "deck_json": str(data), "renderer": stdout.decode().strip()}
