# 架构与实现

本页面向维护者。操作步骤见 [使用指南](USAGE.md)，部署与恢复见 [部署指南](DEPLOYMENT.md)。

## 组件

浏览器/FastAPI 与 Typer CLI → Engine/LangGraph → Gateway → FastMCP stdio → Tools。
业务存储是 `research.sqlite3`，执行快照是 `checkpoints.sqlite3`，产物位于 `data/outputs/<task_id>/`。
配置和模型凭据由 pydantic-settings 读取。模型调用通过 LangChain 的兼容 API/Ollama 适配器；并非自行训练模型。

## 可恢复任务

固定阶段为 prepare → collect → compose → persist。task_id 对应 checkpoint thread_id；失败可恢复未完成步骤。
checkpoint 不保证副作用只发生一次：写入结合 operation_id、稳定记录 ID、事务和 revision，分别处理重试与并发更新。
当前后台任务是单进程 asyncio，不是持久分布式队列。

## 检索与生成

文档按页、段落与 800 字符窗口/650 步长分块；保留页码与段落。
jieba + SQLite FTS5/BM25 召回，另可用本地 multilingual-e5-small 归一化向量余弦召回；按 RRF 融合排名。
向量存为 JSON，当前用 NumPy 精确扫描；无专用向量数据库。
Schema/Pydantic 校验模型 JSON，有限结构纠错，另检查引用 ID 属于输入来源。ID 合法不代表结论得到证据支持。

## 阅读与记忆

PDF.js 提供页面和文字层，选区矩形按页面归一化保存。后端 pypdf 提取原文供检索，无 OCR。
会话历史与知识卡片分离；inbox/confirmed/archived 控制知识整理。独立个人笔记支持分层，核心层由用户手动填写。
项目、材料、笔记、Idea 与实验关联，周报转为结构化大纲，再由 Node/PptxGenJS 渲染可编辑 PPTX。

### 知识一致性

阅读会话绑定文档，当前问题、选段及最近问题用于检索；原文块与历史/知识背景分开传给模型，阅读引用只能来自当前原文证据。

问答卡片按会话和轮次生成稳定 ID，重复保存不覆盖已有人工批注；更新以 revision 检查过期写入。独立个人笔记不随文档级联删除，但来源失效时不能继续作为有效原文证据。

个人复盘基于已确认记录的共同标签：三个不同日期的情境事件/决策可产生行为主题，两条行为记录可产生认知主题。候选仍待人工整理；核心层不接受自动提炼。这是可追溯的整理规则，不是统计因果推断。

## 对话范围与上下文

`ChatContext.prepare` 组合项目说明、显式文档块及允许召回的已确认笔记。`document_mode=auto` 使用项目资料；`selected` 的空列表表示不检索文档，避免取消选择后意外扩大范围。

上下文最多十二条来源、18000 字符，每条最多 2500 字符；最近六轮历史各限制用户/回答长度。当前预算是字符限制，不是精确 token 计数。成功轮保存来源快照和范围，浏览器未发送草稿由 localStorage 保存。

聊天结果检查 source_ids 白名单，保存按 task_id 去重并检查会话 revision。API 拒绝同会话重叠任务；该并发管理以单应用实例为前提。

## 文献关系

直接引用边由引用者指向被引者。结构相似图采用观测邻域集合：R 为参考文献，C 为引用者。

```text
coupling(a,b) = |R(a) ∩ R(b)| / sqrt(|R(a)| × |R(b)|)
co_citation(a,b) = |C(a) ∩ C(b)| / sqrt(|C(a)| × |C(b)|)
score = (coupling + co_citation) / 2
```

空集合分量为零；仅有实际共享来源时创建结构相似边，保留共享 ID 和采样覆盖信息。有限一/二跳邻域产生候选，按到起点的最强乘积路径选取可达节点；没有证据时不使用文本向量补造结构边。

共同前作是被至少两篇图中论文引用的图外文献，共同后续是引用至少两篇图中论文的图外文献。采样受请求预算、候选数、分页与超时约束，不等于全库推荐或完整引用总数。

API：`POST /papers/map`，参数示例：

```json
{"seed":"10.1038/nature14539","limit":20,"candidate_limit":24,"sample_size":50}
```

CLI：`research-agent papers map <论文ID或DOI> --limit 20`。图、论文列表和来源证据写入任务产物，不自动成为知识卡片。

## 验证入口

`tests/test_reading.py`、`test_memory.py`、`test_personal_memory.py` 覆盖阅读与记忆边界；`test_chat.py` 验证来源范围、历史、幂等与并发；`test_bibliometrics.py` 验证结构分数与采样。

协议集成使用真实 stdio MCP；浏览器测试使用隔离数据和 Chrome。模型替身验证流程，真实云模型 smoke 只证明对应请求可用，不代表正式问答质量评测。

## 主要源码

- [API](../src/research_agent/api.py)、[工作流](../src/research_agent/workflows.py)、[存储](../src/research_agent/storage.py)。
- [文档](../src/research_agent/documents.py)、[聊天](../src/research_agent/chat.py)、[个人记忆](../src/research_agent/personal_memory.py)。
- [MCP 客户端](../src/research_agent/mcp_client.py)、[工具服务](../src/research_agent/mcp_server.py)。
- [论文](../src/research_agent/papers.py)、[文献图](../src/research_agent/bibliometrics.py)、[PPT](../src/research_agent/slides.py)。
