# Experiment Checklist

## 常见实验设计检查清单

### 实验设计基础
- [ ] 是否有明确的研究假设（hypothesis）
- [ ] 自变量（independent variable）和因变量（dependent variable）是否定义清晰
- [ ] 是否设置了合理的对照组（control group）
- [ ] 实验规模（样本数/数据量）是否足够支撑结论
- [ ] 是否说明了实验的 scope 和 limitation

### Baseline 与对比
- [ ] Baseline 是否为领域内公认的方法或 SOTA
- [ ] 对比方法是否使用相同的数据集划分和预处理
- [ ] 是否引用了 baseline 的原始论文或官方实现
- [ ] 超参数调优是否对所有方法公平（相同搜索预算）
- [ ] 是否在相同硬件/环境下运行对比实验

### Ablation Study
- [ ] 是否覆盖了模型/系统的所有关键模块
- [ ] 每次只移除/替换一个组件（single-variable control）
- [ ] 是否说明了各模块的贡献度

### 可复现性
- [ ] 数据集是否公开或提供获取方式
- [ ] Random seed 是否固定并报告
- [ ] 环境配置（Python version、framework version、GPU 型号）是否记录
- [ ] 训练和评估脚本是否提供
- [ ] 是否报告了运行时间和计算资源需求

---

## 常见指标说明与合理范围

| 指标 | 领域 | 说明 | 合理范围参考 |
|------|------|------|-------------|
| Accuracy | 分类任务 | 正确预测占总预测的比例 | 取决于数据集难度，CIFAR-10 > 95%，ImageNet > 80% |
| F1 Score | NLP/分类 | Precision 和 Recall 的调和平均 | 取决于任务，NER 通常 85-95% |
| BLEU | 机器翻译/文本生成 | n-gram 匹配度 | 翻译任务 25-45 为合理区间 |
| ROUGE | 文本摘要 | 召回导向的 n-gram 重叠 | ROUGE-L 通常 35-55% |
| FID (Frechet Inception Distance) | 图像生成 | 生成图像与真实图像分布的距离 | 越低越好，SOTA 通常 < 10 |
| Latency | 系统性能 | 请求响应时间 | 取决于场景，API < 200ms，推理 < 1s |
| Throughput | 系统性能 | 单位时间处理请求数 | 取决于硬件和模型规模 |
| Perplexity | 语言模型 | 模型对测试集的困惑度 | 越低越好，GPT-2 level ~20-30 on WikiText |

---

## 对比实验的常见陷阱

### 1. 不公平对比（Unfair Comparison）
- 自己的方法用了更多数据或更大模型
- Baseline 使用了过时的实现或未调优的超参数
- 对比方法未在相同条件下重新运行

### 2. 数据泄露（Data Leakage）
- 训练集和测试集有重叠样本
- 特征工程使用了测试集的统计信息
- Pretrained model 的训练数据包含了评估数据集

### 3. 过拟合 Test Set
- 在 test set 上反复调参（应使用 validation set）
- 只报告最好的一次运行结果，不报告平均值和方差
- Test set 过小，随机波动被当作真实提升

### 4. 选择性报告（Cherry-picking）
- 只报告有利的指标，隐藏不利指标
- 只展示成功的 case study，不分析 failure case
- 更换评估指标以获得更好看的数字

### 5. 统计显著性缺失
- 只运行一次实验，不报告多次运行的均值和标准差
- 指标提升在误差范围内（如 ±0.5% 的提升但 std 为 1%）
- 未进行统计检验（t-test、Wilcoxon test 等）
