# 支持 MCP、Function Call、Skills 与多模态 RAG 的智能体系统 PRD

## 执行摘要

本系统采用分层架构，而不是依赖单一 agent 框架覆盖所有能力：

- **LangGraph 或等价编排层**：负责状态机、checkpoint、会话恢复、人工审批与长任务恢复。
- **Function Call Registry**：负责严格 JSON Schema 工具调用、风险分级、幂等、重试与审计。
- **MCP Gateway**：负责把外部业务系统、检索服务、通讯服务标准化暴露为 tools、resources、prompts。
- **Agent Skills**：负责领域 SOP、参考资料和脚本的渐进式加载。
- **多模态 RAG**：负责文本、页面视觉、对象级证据的检索、融合和重排。
- **记忆系统**：负责工作记忆、滚动摘要、episodic memory、semantic memory 与身份/行为记忆。

## 产品目标

构建一个可长期运行、可接外部系统、可稳定调用工具、能对复杂文档和多模态知识做检索、还能跨会话保持行为一致性的智能体平台。

该仓库首期只交付工程骨架和接口规范，后续按阶段接入真实模型、MCP server、向量库、业务 API 和外部渠道。

## 推荐技术栈

| 层 | 默认选择 | 说明 |
|---|---|---|
| 编排 | LangGraph | durable execution、checkpoint、human-in-the-loop |
| API | FastAPI | 会话入口、工具入口、健康检查 |
| 工具调用 | OpenAI-compatible function registry | `strict: true` JSON Schema、审批、幂等 |
| MCP | MCP Gateway | tools/resources/prompts 标准化接入 |
| Skills | `SKILL.md` | progressive disclosure，领域 SOP |
| 文档摄取 | Docling / MinerU | PDF、Office、图片、表格、公式解析 |
| 文本检索 | Qdrant + BGE-M3 | dense+sparse hybrid，多语言和中文友好 |
| 页面视觉检索 | ColPali / ColQwen | 捕捉布局、图表、公式、截图 |
| 重排 | BGE Reranker | 提升证据排序质量 |
| 短期记忆 | Redis + checkpoint | thread state 与 session cache |
| 长期记忆 | Postgres + Qdrant + Markdown | 结构化、向量化和人工可读并存 |
| 对象存储 | MinIO / S3 | 保存原文档、页面图像和附件 |

## 首期范围

- 仓库结构、文档与接口规范。
- Python 包骨架和类型模型。
- 工具注册、Skills 加载、RAG、记忆、渠道事件、审计模型。
- 示例配置、示例技能、记忆文件模板。
- 基础测试和评估说明。

## 非首期范围

- 不实现完整 LangGraph 生产编排。
- 不接入真实模型或真实业务系统。
- 不执行远程 GitHub 创建和推送。
- 不上线生产环境。
