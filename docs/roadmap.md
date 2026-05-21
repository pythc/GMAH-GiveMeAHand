# 实施路线图

## 阶段 1：工程骨架与接口规范

交付：

- 仓库结构、文档、配置示例。
- Python 包骨架。
- 工具、MCP、Skills、RAG、记忆、渠道、审计模型。
- 基础测试与评估占位。

验收：

- 项目可安装。
- 基础测试通过。
- 工具 schema、技能加载、渠道事件和记忆模型有测试覆盖。

## 阶段 2：MVP 工具与会话记忆

交付：

- LangGraph thread state 和 checkpoint。
- 批改系统最小工具集。
- 草稿保存和人工审批流程。
- Redis 短期记忆。

验收：

- 可读取作业、生成反馈草稿、审批后回写。
- 工具调用可回放、可审计、可幂等。

## 阶段 3：文本 RAG

交付：

- 文档摄取管道。
- 文本索引和 reranker。
- 检索评测数据集。

验收：

- recall@k、MRR、faithfulness 达到业务基线。
- 回答带可追溯引用。

## 阶段 4：多模态 RAG 与 Skills

交付：

- 页面视觉索引。
- 文本 + 视觉融合检索。
- 批改复核和渠道运营 Skills。

验收：

- 图表、公式、截图类问题召回明显优于纯文本基线。
- Skills 触发测试通过。

## 阶段 5：长期记忆与渠道接入

交付：

- episodic/semantic memory。
- `AGENTS.md`、`SOUL.md`、`MEMORY.md` 生命周期。
- QQ/Webhook/邮件 channel adapter。

验收：

- 长会话恢复成功率达标。
- 外部消息去重、权限、审计和风控可用。
