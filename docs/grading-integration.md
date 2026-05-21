# 批改系统适配规范

## 资源与工具映射

| 能力 | 推荐暴露形式 | 风险 | 说明 |
|---|---|---|---|
| 课程读取 | MCP resource | low | 稳定上下文 |
| 作业读取 | MCP resource | low | 作业说明、截止时间、附件 |
| Rubric 读取 | MCP resource | low | 评分标准和版本 |
| 学生提交获取 | MCP tool / function tool | medium | 需权限校验 |
| 历史批注查询 | RAG source | low | 提升一致性 |
| 反馈草稿保存 | function tool | medium | 需幂等 |
| 正式成绩发布 | function tool | high | 必须人工审批 |
| 学生通知 | channel tool | high | 必须审计和防误发 |

## 高风险工具要求

- `approval_policy` 必须为 `human_required`。
- 必须有 `idempotency_key_source`。
- 必须记录审批人、审批时间、工具入参摘要和外部系统响应摘要。
- 发布前必须校验 rubric 版本和 submission 状态。

## SQL 安全要求

- 所有数据库查询必须使用参数化查询。
- 不允许拼接用户输入生成 SQL。
- `orderBy`、`sortBy`、`groupBy`、`sortDirection` 等动态字段必须先做白名单校验。

## MVP 流程

1. 读取作业、rubric 和学生提交。
2. 检索历史批注与常见错误。
3. 生成反馈草稿。
4. 人工复核。
5. 保存草稿或发布成绩。
6. 记录审计日志并更新会话摘要。
