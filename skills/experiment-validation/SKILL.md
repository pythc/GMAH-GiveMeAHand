---
name: experiment-validation
description: This skill should be used when reviewing student work that contains experimental data, performance metrics, comparison results, ablation studies, or any empirical evaluation that requires scientific validity verification.
---

# Experiment Validation Skill

## Purpose

验证学生实验的科学性和可信度。确保实验设计合理、baseline 对比公平、结果呈现规范、结论有数据支撑，并判断实验是否具备可复现性。

## Workflow

1. 检查是否有明确的实验设计（hypothesis、自变量/因变量、control group）。
2. 验证 baseline/对比方法是否合理且被正确引用（原论文、官方实现、公开 benchmark）。
3. 检查 ablation study 是否覆盖了模型或系统的关键模块，避免遗漏核心组件。
4. 验证结果呈现是否包含指标定义、置信区间（confidence interval）或误差范围（error bar/std）。
5. 检查实验是否可复现：数据集来源、random seed、环境配置（GPU/framework version）、训练/评估脚本是否提供。
6. 判断结论是否被实验数据充分支撑，避免过度宣称（overclaim）或选择性报告（cherry-picking）。

## Safety Rules

- 不在缺少原始数据或实验日志的情况下推断实验有效性。
- 不将未验证的数字作为最终结论，需标注数据来源和验证状态。
- 对于差异微小的指标提升（如 < 1% accuracy），标注"统计显著性待验证"。
- 如果无法判断实验公平性（如缺少 baseline 细节），应明确标注而非默认通过。

## References

- Load `references/experiment-checklist.md` for experiment design checklist and common metric explanations.
