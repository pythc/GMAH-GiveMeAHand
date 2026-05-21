# Agent Workflow

`agent-workflow` 是一个面向 MCP、Function Call、Agent Skills、多模态 RAG、会话记忆与外部渠道适配的智能体平台工程骨架。

首期目标不是一次性实现完整生产系统，而是把 PRD 拆解为可维护的仓库结构、接口规范、基础代码、配置示例和测试基线。

## 架构原则

- **编排与能力解耦**：LangGraph 负责会话状态、恢复和人工审批；工具、检索、记忆、渠道通过接口接入。
- **MCP 与 Function Call 分层**：MCP 解决外部系统如何暴露能力，Function Call Registry 解决模型如何按 schema 调用能力。
- **Skills 与 Tools 分工**：Skills 承载领域 SOP 与参考资料，Tools 承载可执行动作和副作用。
- **多模态 RAG 双轨索引**：文本索引处理段落、代码、结构化字段；页面视觉索引处理图表、公式、截图和复杂排版。
- **记忆分层治理**：工作记忆、滚动摘要、episodic memory、semantic memory 与身份/行为记忆分开管理。
- **安全默认开启**：高风险工具必须带审批策略、幂等键和审计元数据；配置不得硬编码真实密钥。

## 快速开始

```bash
cd /Users/alex/CodeBuddy/20260518153547/agent-workflow
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

启动本地依赖与应用容器：

```bash
docker compose up --build -d
```

仅构建应用镜像：

```bash
docker build -t agent-workflow:local .
```

本地非容器方式启动 API 骨架：

```bash
uvicorn agent_workflow.api.app:create_app --factory --host 0.0.0.0 --port 8080 --reload
```

启动前端控制台开发服务：

```bash
cd web
npm install
npm run dev
```

前端默认地址：`http://127.0.0.1:5173`。容器化启动后，前端控制台地址为 `http://127.0.0.1:3000`。

## 前端控制台

`web/` 使用成熟前端栈 `React + Vite + TypeScript + Ant Design`，包含：

- 总览仪表盘：健康检查、工具数量、待审批数量。
- 模型设置：运行时填写 Base URL、模型名和 API Key；密钥只保存在后端进程内存中，不落盘。
- 模型调用：调用 `/model/chat`。
- 会话/工具：创建会话、普通编排或 LangGraph 编排执行工具。
- 审批：查看 pending approval，并批准或拒绝。
- RAG：文档摄取、文本检索、视觉检索、融合检索。
- MCP：能力发现、tool 调用、resource 读取。

## MVP API

当前已打通一条可测试的批改系统 MVP 纵切：会话入口、Function Tool 配置加载、批改 mock adapter、审批、幂等、审计和 checkpoint。

已接入真实基础设施边界：

- `LangGraphSessionRuntime`：使用真实 `langgraph.graph.StateGraph` 执行会话 turn。
- `RedisCheckpointStore` / `RedisIdempotencyStore`：配置 `REDIS_URL` 后启用 Redis 会话与幂等持久化。
- `PostgresApprovalStore` / `PostgresAuditStore`：配置 `POSTGRES_DSN` 后启用 Postgres 审批与审计持久化。
- `QdrantRagGateway`：配置 `QDRANT_URL` 后启用 Qdrant 文本/页面视觉向量检索。
- `StreamableHttpMcpGateway`：按 `configs/mcp-servers.example.yaml` 连接远程 MCP server，并执行 allowlist 校验。
- `OpenAICompatibleChatClient`：默认接入火山方舟 OpenAI 兼容接口，模型为 `doubao-seed-2-0-code-preview-260215`，密钥从 `MODEL_API_KEY` 读取。

常用接口：

- `POST /sessions`：创建会话。
- `POST /sessions/run`：追加用户消息，并可显式触发一个工具调用。
- `POST /sessions/run-langgraph`：通过 LangGraph StateGraph 执行会话 turn。
- `GET /sessions/{thread_id}`：查询会话状态。
- `GET /sessions/tools/list`：查看已加载工具。
- `GET /approvals/pending`：查看待审批工具调用。
- `POST /approvals/{approval_id}/decide`：批准或拒绝高风险工具。
- `POST /rag/ingest`：摄取文本和页面/图片证据。
- `POST /rag/retrieve/text`：文本检索。
- `POST /rag/retrieve/visual`：页面视觉检索。
- `POST /rag/retrieve/fused`：文本 + 视觉融合检索。
- `GET /mcp/capabilities`：发现远程 MCP 能力。
- `POST /mcp/tools/call`：调用 allowlisted MCP tool。
- `POST /mcp/resources/read`：读取 allowlisted MCP resource。
- `POST /model/chat`：正式调用配置的 OpenAI-compatible 聊天模型。

示例：

```bash
curl -X POST http://127.0.0.1:8080/sessions/run \
  -H 'content-type: application/json' \
  -d '{
    "user_id": "teacher-1",
    "message": "保存反馈草稿",
    "tool_call": {
      "tool_name": "save_feedback_draft",
      "arguments": {
        "submission_id": "submission-1",
        "draft_revision": "r1",
        "feedback_markdown": "结构清晰，建议补充评估指标。"
      }
    }
  }'
```

模型调用示例：

```bash
curl -X POST http://127.0.0.1:8080/model/chat \
  -H 'content-type: application/json' \
  -d '{
    "messages": [{"role": "user", "content": "用一句话介绍这个系统"}],
    "temperature": 0.2
  }'
```

## 模块地图

- `src/agent_workflow/api`：FastAPI 入口、会话/审批/RAG/MCP 路由。
- `src/agent_workflow/orchestrator`：会话状态、Redis checkpoint、LangGraph runtime、审批中断点和 MVP 编排服务。
- `src/agent_workflow/tools`：Function Tool Registry、配置加载、执行边界、JSON Schema、风险、审批和 Redis 幂等元数据。
- `src/agent_workflow/integrations`：外部业务系统适配器；当前包含批改系统 mock adapter。
- `src/agent_workflow/evaluation`：课题产物综合评价 rubric、评分模型和建议生成服务。
- `src/agent_workflow/mcp`：MCP Gateway 配置加载、Streamable HTTP JSON-RPC 客户端与本地 MCP 测试服务器。
- `src/agent_workflow/llm`：OpenAI-compatible 聊天模型客户端，默认面向火山方舟豆包模型。
- `src/agent_workflow/skills`：`SKILL.md` 扫描与渐进式加载。
- `src/agent_workflow/rag`：文本/页面摄取、hash embedding、本地检索、Qdrant 检索和融合重排。
- `src/agent_workflow/storage`：Postgres 审批与审计持久化。
- `src/agent_workflow/memory`：工作记忆、摘要、长期记忆和身份文件模型。
- `src/agent_workflow/channels`：QQ、OneBot/NapCat、Webhook、邮件等渠道事件归一化模型，以及压缩包安全检查。
- `src/agent_workflow/security`：审批闸门、审计事件、风险等级和脱敏标记。

## 文档

详见 `docs/`：

- `docs/prd.md`
- `docs/architecture.md`
- `docs/modules.md`
- `docs/rag-design.md`
- `docs/memory-design.md`
- `docs/channel-adapter.md`
- `docs/grading-integration.md`
- `docs/security.md`
- `docs/roadmap.md`

## 安全边界

- 不提交 `.env`、密钥、访问令牌或真实用户数据。
- 所有写操作工具必须声明 `risk_level`、`approval_policy` 和 `idempotency_key_source`。
- SQL 示例必须使用参数化查询；动态字段必须做白名单校验。
- 记忆写入必须记录来源、置信度和敏感数据标记。

## 当前状态

该仓库已从工程骨架推进到可运行 MVP：批改工具链路、LangGraph 会话入口、Redis/Postgres 持久化适配、MCP HTTP Gateway、文本/页面多模态 RAG 摄取与 Qdrant 检索边界均已具备。后续重点是接入真实 embedding/reranker、真实 MCP server、生产鉴权和渠道 adapter。
