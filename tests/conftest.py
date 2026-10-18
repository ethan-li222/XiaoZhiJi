import json

import httpx
import numpy as np
import pytest

from research_agent.config import Settings
from research_agent.tools import Tools
from research_agent.workflows import Engine


class FakeEmbedding:
    identity = "test-embedding"

    def encode(self, texts, query=False):
        result = []
        for text in texts:
            v = np.array(
                [1 + text.count("引用"), 1 + text.count("耦合"), 1 + text.count("共引")],
                dtype=float,
            )
            result.append((v / np.linalg.norm(v)).tolist())
        return result


class FakeModel:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.invalid = False

    async def generate(self, instruction, payload, schema):
        self.calls.append(payload)
        if self.fail:
            raise ValueError("temporary model failure")
        if schema.__name__ == "ChatReply":
            return schema(
                answer="可以先明确目标，再拆分为可验证的小步骤。",
                source_ids=["invented"]
                if self.invalid
                else [s["id"] for s in payload["sources"][:1]],
                followups=["你最希望先解决哪一步？"],
            )
        if schema.__name__ == "ResearchSynthesis":
            identifier = "invented" if self.invalid else payload["sources"][0]["id"]
            return schema(
                overview="现有笔记提示研究问题仍需验证。",
                findings=[{"text": "已观察到的局限", "source_ids": [identifier]}],
                candidate_ideas=[
                    {
                        "title": "候选假设",
                        "hypothesis": "改变检索策略可能改善表现",
                        "difference": "增加可验证对照",
                        "source_ids": [identifier],
                        "validation": "与基线比较",
                        "uncertainty": "新颖性待核验",
                    }
                ],
            )
        if schema.__name__ == "HabitAdvice":
            return schema(
                observations=[
                    {
                        "interpretation": "记录了阅读时间",
                        "metric_keys": ["invented" if self.invalid else "self_reported_minutes"],
                    }
                ],
                options=[
                    {
                        "action": "每周留出验证假设的时间",
                        "benefit": "增加可检验产出",
                        "cost": "减少部分泛读",
                        "uncertainty": "需观察两周",
                        "metric_keys": ["ideas_created"],
                    }
                ],
                trial_plan="试行两周并复盘",
            )
        if schema.__name__ == "GroundedAnswer":
            return schema(
                answer="文献耦合是共享参考文献。",
                evidence_ids=["invented"] if self.invalid else [payload["evidence"][0]["id"]],
            )
        if schema.__name__ == "ReportDraft":
            return schema(
                title="前沿报告",
                sections=[
                    {
                        "title": "技术变化",
                        "text": "依据发布信息生成的摘要。",
                        "source_ids": ["invented"]
                        if self.invalid
                        else [payload["sources"][0]["id"]],
                    }
                ],
            )
        if schema.__name__ == "Slide":
            return schema(
                title="已修改", bullets=["重点技术局限"], source_ids=payload["slide"]["source_ids"]
            )
        pages = int(instruction.split("生成 ")[1].split(" 页")[0])
        return schema(
            title="科研汇报",
            slides=[
                {
                    "title": f"第 {i + 1} 页",
                    "bullets": ["引用保留"],
                    "source_ids": [s["id"] for s in payload["sources"]],
                }
                for i in range(pages)
            ],
        )


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        data_dir=tmp_path,
        embedding_dir=tmp_path / "missing",
        tool_transport="local",
        http_timeout=2,
    ).prepare()


@pytest.fixture
def model():
    return FakeModel()


@pytest.fixture
def tools(settings):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    )
    return Tools(settings, client=client, embedder=FakeEmbedding())


@pytest.fixture
def engine(settings, model, tools):
    return Engine(settings, model=model, local_tools=tools)


async def run(engine, action, params):
    task = engine.create(action, params)
    result = await engine.run(task["id"])
    assert result["status"] == "completed", json.dumps(result, ensure_ascii=False)
    return result["result"]
