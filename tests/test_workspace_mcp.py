from research_agent.mcp_client import Gateway


async def test_workspace_nested_actions_over_real_stdio(settings):
    settings.tool_transport = "stdio"
    async with Gateway(settings).open() as gateway:
        project = (await gateway.call("workspace.project.save", {"name": "MCP workspace"}))["entry"]
        material = await gateway.call(
            "workspace.import",
            {
                "project_id": project["id"],
                "source": "mcp-text",
                "text": "检索需要基线验证。",
            },
        )
        note = await gateway.call(
            "workspace.annotation.save",
            {
                "project_id": project["id"],
                "document_id": material["document"]["id"],
                "selection": "检索需要基线验证。",
                "text": "设计控制变量实验",
            },
        )
        idea = await gateway.call(
            "workspace.idea.save",
            {
                "project_id": project["id"],
                "title": "MCP idea",
                "hypothesis": "有待验证",
                "source_ids": [note["entry"]["id"]],
            },
        )
        assert idea["entry"]["source_ids"] == [note["entry"]["id"]]
        weekly = await gateway.call("workspace.weekly", {"project_id": project["id"], "days": 7})
        assert weekly["stats"]["metrics"]["annotations"] == 1
        assert weekly["deck"]["slides"]
