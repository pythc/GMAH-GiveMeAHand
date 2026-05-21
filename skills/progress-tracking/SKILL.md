---
name: progress-tracking
description: This skill should be used when the same project or repository has repeated submissions, when comparing against previous review feedback, or when tracking iterative improvement across multiple review cycles.
---

# Progress Tracking Skill

## Purpose

追踪学生课题的迭代进度，通过对比历史评价记录和 git 提交历史，判断是否有实质性改进，并为未改进的情况提供具体的下一步行动建议。

## Workflow

1. 通过 `get_review_history` 获取该学生/课题的上次评价记录，提取上次指出的问题列表和改进建议。
2. 通过 `git_history` 对比 commit 时间线，识别自上次评价以来的新增 commit，了解改动范围。
3. 逐条对比上次指出的问题和建议是否被解决：标记 resolved / partially resolved / unresolved。
4. 量化改进：统计新增代码行数、新增测试用例、新增文档、修复的 issue 数量、删除的冗余代码。
5. 综合判断 `improved=true/false` 并给出理由：需要至少一个关键问题被实质性解决才能标记为 improved。
6. 如果 `improved=false`，给出具体的下一步行动建议，按优先级排列。

## Safety Rules

- 必须基于 git diff 或文件对比得出结论，不能凭印象或仅凭 commit message 判断。
- 如果无法访问上次的具体文件快照，标注"基于历史评价文字对比，未进行代码级验证"。
- 不要因为小改动就标记 `improved=true`，需要实质性解决至少一个关键问题（如核心功能缺陷、重大设计问题）。
- 区分"表面改动"和"实质改进"：仅修改 README、添加注释、调整格式不算实质性改进。
- 如果 commit 历史被 force push 重写，需标注并谨慎对比。

## References

- Load `references/improvement-criteria.md` for improvement judgment criteria and common false-improvement patterns.
