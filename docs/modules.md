# 模块规格

## `api`

提供 FastAPI 应用入口、健康检查和后续会话 API 挂载点。首期不绑定具体模型或业务系统。

## `orchestrator`

维护会话状态：thread、消息、工具结果、审批状态、摘要引用和恢复点。后续可接 LangGraph checkpointer。

## `tools`

统一管理 function tools：

- `name` 与 `description`
- 严格 JSON Schema 参数
- 风险等级：`low`、`medium`、`high`
- 审批策略：`none`、`policy_based`、`human_required`
- 幂等键来源
- mock 执行入口和审计钩子

## `mcp`

定义 MCP Gateway 抽象，按 tools/resources/prompts 三类能力管理外部系统接入。

## `skills`

扫描 `skills/*/SKILL.md`，先加载名称和描述，命中任务后再加载完整 skill 内容、参考资料或脚本。

## `rag`

定义多模态 RAG 接口：

- 文本检索
- 页面视觉检索
- 结果融合
- 重排
- 上下文构建
- 引用与证据返回

## `memory`

定义工作记忆、会话摘要、episodic memory、semantic memory、identity memory 的类型和写入边界。

## `channels`

定义统一渠道事件模型，将 QQ、OneBot、Webhook、邮件等事件归一化为一致结构。

## `security`

集中定义风险等级、审批状态、审计事件、敏感数据标记和工具副作用记录。
