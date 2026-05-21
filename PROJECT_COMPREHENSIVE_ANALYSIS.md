# agent-workflow 项目完整系统分析文档

**生成时间**：2026-05-21  
**项目路径**：`/Users/alex/CodeBuddy/20260518153547/agent-workflow`  
**分析范围**：评价系统、工具日志、RAG 摄取系统

---

## 📋 目录

1. [项目概览](#1-项目概览)
2. [核心模块详解](#2-核心模块详解)
3. [完整的评价流程](#3-完整的评价流程示例)
4. [数据流与架构](#4-数据流与架构图)
5. [关键交互点](#5-关键交互点总结)
6. [部署与配置](#6-部署与配置)
7. [性能与限制](#7-性能与限制)
8. [扩展点](#8-扩展点)

---

## 1. 项目概览

这是一个**多模态课题产物评价系统**，通过 QQ/OneBot 集成接收课题产物，使用规则引擎和 AI 智能体进行综合评价。

### 核心特性：
- 📊 **多维度评价系统**（基于加权评分卡）
- 🤖 **AI 智能体代码审查**（工具循环架构）
- 📦 **压缩包自动解析与评价**
- 🔗 **GitHub 仓库深度分析**
- 📚 **RAG 文档摄取与检索**
- 💬 **QQ 自动回复与进度汇报**
- 📋 **评价历史追踪**（基于 XLSX）

### 主要文件：
```
src/agent_workflow/
├── evaluation/
│   ├── service.py              # 规则引擎
│   ├── models.py               # 数据模型
│   ├── repository.py           # 仓库分析器
│   ├── repository_agent.py     # AI 工具循环
│   └── history.py              # 评价历史
├── rag/
│   ├── models.py               # RAG 数据模型
│   ├── ingestion.py            # 文档分块
│   ├── gateway.py              # 网关接口
│   └── api/routes/rag.py       # RAG 路由
└── api/routes/
    ├── qq.py                   # QQ/OneBot 集成
    └── evaluation.py           # 评价 API
```

---

## 2. 核心模块详解

### 2.1 评价系统 (`evaluation/`)

#### 2.1.1 评价服务 (`service.py`)

**核心功能**：规则驱动的确定性评价引擎

**关键类**：
```python
ProjectEvaluationService
  └─ evaluate(request: ProjectEvaluationRequest) -> ProjectEvaluationResult
```

**评价流程**：
1. **产物分析** → 统计产物数量、类型覆盖率
2. **关键词匹配** → 按维度逐个检查关键词命中率
3. **评分计算** → 基础分 42 + min(命中数, 6) * 8
4. **缺失检查** → 检测代码仓库、文档、测试等关键产物
5. **加权聚合** → 8 个维度加权求和（总分 0-100）

**默认评分卡（DEFAULT_RUBRIC）**：

| 维度 | 权重 | 说明 |
|------|------|------|
| 研究问题与论证质量 | 0.18 | 课题目标、方法、实验、结论 |
| 技术深度与实现完整性 | 0.16 | 架构、算法、系统实现 |
| 证据链与可追溯性 | 0.14 | 报告、论文、代码、数据相互印证 |
| 可复现性 | 0.14 | 环境、依赖、脚本、Docker |
| 表达与展示质量 | 0.12 | 写作、图表、PPT、视频 |
| 代码质量与仓库治理 | 0.12 | 测试、CI、类型检查、安全 |
| 创新性与对比分析 | 0.08 | 创新点、基线对比、消融 |
| 风险、伦理与安全 | 0.06 | 隐私、安全、偏差、合规 |

**关键词字典（KEYWORDS）**：
- 每个维度有对应的中英文关键词列表
- 计数方式：检查关键词是否出现在产物文本中

**评价结果**：
```python
ProjectEvaluationResult(
  overall_score: float              # 0-100
  summary: str                      # 综合评价摘要
  coverage: dict[str, bool]         # 产物类型覆盖
  artifact_assessments: list[...]   # 每个产物评估
  criterion_assessments: list[...]  # 每个维度得分
  strengths: list[str]              # 优势
  weaknesses: list[str]             # 不足
  recommendations: list[str]        # 改进建议（最多 8 个）
  next_steps: list[str]             # 后续行动
)
```

**评分规则详解**：
- **基础分**：42
- **命中加分**：每个关键词 +8（最多 6 个，上限 48）
- **缺失减分**：
  - 无代码仓库（code_quality）: -18
  - 无 PPT/演示: -8 each
  - 无视频/讲解稿: -8 each
  - 产物覆盖不完整: -min(20, 缺失数 * 4)
  - 缺少复现文档: -12
- **最终范围**：max(0, min(100, 计算结果))

---

#### 2.1.2 数据模型 (`models.py`)

**产物类型（ArtifactKind）**：
```python
enum ArtifactKind(StrEnum):
    REPORT              # 研究报告
    PAPER               # 学术论文
    PRESENTATION        # PPT/演示材料
    VIDEO               # 视频/讲解
    CODE_REPOSITORY     # GitHub 代码仓库
    DATASET             # 数据集
    EXPERIMENT_LOG      # 实验日志
    OTHER               # 其他
```

**核心 Pydantic 模型**：

```python
# 输入产物
class ArtifactInput(BaseModel):
    artifact_id: str                    # 唯一标识
    kind: ArtifactKind                  # 产物类型
    title: str                          # 产物标题
    uri: str | None = None              # 文件/仓库地址
    text: str | None = None             # 文本内容
    transcript: str | None = None       # 视频转写
    repository_summary: str | None = None  # 仓库总结
    metadata: dict[str, Any] = {}       # 自定义元数据
    
    # 验证：至少包含一种内容
    @model_validator
    def require_reviewable_content(self):
        if not any([self.uri, self.text, self.transcript, 
                   self.repository_summary, self.metadata]):
            raise ValueError("产物必须包含可评审的内容")

# 输入评价请求
class ProjectEvaluationRequest(BaseModel):
    topic_title: str                    # 课题名
    topic_goal: str                     # 评价目标
    artifacts: list[ArtifactInput]      # 产物列表
    rubric: EvaluationRubric | None = None  # 自定义评分卡

# 评分维度
class RubricCriterion(BaseModel):
    criterion_id: str                   # 维度 ID
    name: str                           # 维度名
    description: str                    # 描述
    weight: float                       # 权重（>0, ≤1）

# 评分卡
class EvaluationRubric(BaseModel):
    name: str
    criteria: list[RubricCriterion]
    
    @model_validator
    def validate_weights(self):
        total = sum(c.weight for c in self.criteria)
        if not 0.99 <= total <= 1.01:
            raise ValueError("权重和必须为 1.0")
```

---

#### 2.1.3 仓库分析器 (`repository.py`)

**功能**：安全地克隆和分析 GitHub 仓库（无代码执行）

**核心类**：
```python
class RepositoryAnalyzer:
    def analyze_url(url: str) -> RepositorySummary
    def summarize_path(path: Path, *, source_url: str) -> RepositorySummary
```

**安全限制**：
- ✅ 仅允许 GitHub HTTP(S) URL
- 🔒 浅克隆（`--depth=1`）
- 🚫 跳过目录：`.git`, `node_modules`, `.venv`, `__pycache__` 等
- 📊 最多列出 600 个文件
- 📄 单文件最大 8KB，预览最多 60KB

**分析步骤**：
1. 规范化 GitHub URL → 验证 owner/repo
2. 创建临时工作区
3. 浅克隆仓库（超时 60 秒）
4. 列出文件并分类
5. 识别重要文件（README、Dockerfile、pyproject.toml 等）
6. 识别测试文件、CI 文件
7. 构建格式化目录树
8. 生成文本预览

**输出（RepositorySummary）**：
```python
class RepositorySummary(BaseModel):
    source_url: str                     # 仓库 URL
    local_path: str | None              # 本地路径（输出时为 None）
    file_count: int                     # 文件总数
    important_files: list[str]          # 重要文件（最多 30）
    code_files: list[str]               # 代码文件（最多 50）
    test_files: list[str]               # 测试文件（最多 30）
    ci_files: list[str]                 # CI 文件（最多 20）
    directory_tree: list[str]           # 格式化目录树（最多 120）
    tool_trace: list[str]               # 工具执行轨迹
    text_preview: str                   # 关键文件内容预览
    
    def to_artifact() -> ArtifactInput   # 转换为产物
    def to_review_text() -> str          # 转换为评审文本
```

---

#### 2.1.4 智能体仓库审查 (`repository_agent.py`)

**功能**：AI 驱动的交互式代码审查（工具循环）

**核心类**：
```python
class AgenticRepositoryReviewer:
    def review_url(
        url: str,
        topic_title: str,
        topic_goal: str,
        chat_client: OpenAICompatibleChatClient | None,
        agent_system_prompt: str,
        rule_evaluation: ProjectEvaluationResult | None = None,
        progress_callback: RepositoryProgressCallback | None = None,
        tool_log_callback: RepositoryToolLogCallback | None = None,
        rag_callback: RepositoryRagCallback | None = None,
    ) -> AgenticRepositoryReview
```

**工具循环架构**：
```
初始化 
  ├─ 克隆仓库
  ├─ 列出文件
  ├─ AI 循环（最多 40 次）
  │  ├─ clone_repository
  │  ├─ list_files
  │  ├─ read_file（最多 80 个，总 180KB）
  │  ├─ inspect_archive
  │  ├─ retrieve_rag
  │  ├─ get_review_history
  │  ├─ update_review_history
  │  ├─ send_progress
  │  └─ final_answer
  └─ 清理工作区
```

**工具调用格式**：
```json
{
  "tool": "工具名",
  "arguments": {...}
}
```

**资源限制**：
- ⏰ 最多 40 次工具调用
- 📂 最多检查 80 个文件
- 📄 单文件最大 12KB
- 📊 总字符数最大 180KB
- ⌛ 克隆超时：90 秒

**观察记录**：
```python
class RepositoryToolObservation(BaseModel):
    tool: str                          # 工具名
    input: dict[str, Any]              # 输入参数
    output: str                        # 输出结果

class RepositoryFileEvidence(BaseModel):
    path: str                          # 仓库内相对路径
    chars: int                         # 字符数
    content: str                       # 文件内容
```

**最终输出**：
```python
class AgenticRepositoryReview(BaseModel):
    source_url: str
    final_review: str                  # AI 评价（最多 4000 字）
    inspected_files: list[str]
    observations: list[RepositoryToolObservation]
    file_evidence: list[RepositoryFileEvidence]
    
    def to_artifact() -> ArtifactInput  # 转换为产物
    def to_evidence_text() -> str       # 转换为证据文本
```

---

#### 2.1.5 评价历史 (`history.py`)

**功能**：追踪仓库评价历史（基于 XLSX）

**存储格式**：
```
┌─────────┬──────────┬───────┬───────┬────────┬──────────┬────────┐
│ 仓库链接 │ 课题名  │ 评分 │ 评价 │ 更新时间 │ 工具摘要 │ 次数 │
└─────────┴──────────┴───────┴───────┴────────┴──────────┴────────┘
```

**核心类**：
```python
class ReviewHistoryStore:
    def get(repo_url: str) -> ReviewHistoryRecord | None
    def update(
        *,
        repo_url: str,
        topic_name: str,
        review: str,
        score: float | None,
        improved: bool,                 # 是否有明显优化
        tool_summary: str = "",
    ) -> ReviewHistoryUpdateResult

# 更新策略：
# - 如果 improved=False：不写 Excel，返回现有记录
# - 如果 improved=True 或首次：写 Excel，增加评价计数
```

---

### 2.2 工具日志系统 (`api/routes/qq.py`)

#### 日志数据模型

```python
class QqToolLogEntry(BaseModel):
    timestamp: str                     # ISO 8601
    conversation_id: str               # "group:123" 或 "private:456"
    tool: str                          # 工具名称
    target: str | None = None          # URL、路径、查询等
    status: str                        # "success" 或 "failed"
    detail: str | None = None          # 错误/消息（最多 500 字）
    arguments: dict[str, Any] = {}     # 工具调用参数
```

#### 日志记录流程

**日志回调函数** (`_build_tool_log_callback`)：
```python
def callback(tool: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
    # 1. 创建日志条目
    entry = QqToolLogEntry(
        timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
        conversation_id=normalized.conversation_id,
        tool=tool,
        target=_tool_target(arguments),  # 从参数提取目标
        status="success" if result.get("ok") else "failed",
        detail=str(
            result.get("error") or result.get("message") 
            or result.get("reason") or ""
        )[:500],
        arguments=arguments,
    )
    
    # 2. 追加到全局列表
    _tool_logs.append(entry.model_dump())
    
    # 3. 维持最多 500 条日志
    del _tool_logs[:-500]
```

**调用链**：
```
qq.py: _build_tool_log_callback(normalized)
  │
  └──> repository_agent.py: _execute_tool()
       │
       └──> if tool_log_callback is not None:
            tool_log_callback(tool, arguments, result)
```

**查询端点**：
```
GET /qq/tool-logs?limit=100
  返回最后 100 条日志（最多 500）
```

**日志目标提取** (`_tool_target`)：
```python
# 按优先级：url > path > query > topic_name > message[:60]
# 用于标识操作目标，简化日志阅读
```

---

### 2.3 RAG 摄取系统 (`rag/`)

#### 2.3.1 RAG 模型 (`models.py`)

**内容模态（Modality）**：
```python
enum Modality(StrEnum):
    TEXT                # 文本块
    IMAGE               # 图像
    PAGE                # PDF 页面
    AUDIO_TRANSCRIPT    # 音频转写
    TABLE               # 表格
```

**摄取数据流**：

```
IngestDocument（源文档）
├─ source_id: str                   # 源标识
├─ text: str | None                 # 整体文本
├─ pages: list[IngestPage]          # 页面列表
│  ├─ page_number: int [≥1]
│  ├─ artifact_uri: str
│  ├─ text: str | None
│  └─ metadata: dict
├─ tenant_id: str | None            # 租户 ID
└─ metadata: dict

        ↓ chunk_documents()

IngestChunk（分块结果）
├─ chunk_id: str           # 块唯一 ID
├─ source_id: str
├─ modality: Modality
├─ content: str | None
├─ artifact_uri: str | None
├─ tenant_id: str | None
└─ metadata: dict
```

**检索流程**：

```
RetrievalQuery（检索请求）
├─ query: str                      # 查询文本
├─ tenant_id: str | None
├─ filters: dict                   # 元数据过滤
├─ text_top_k: int [1-100]
└─ visual_top_k: int [0-100]

        ↓ retrieve_fused()

RetrievalResult（检索结果）
├─ query: RetrievalQuery
└─ evidence: list[RetrievalEvidence]
   ├─ source_id: str
   ├─ modality: Modality
   ├─ score: float [≥0]
   ├─ content: str | None
   ├─ artifact_uri: str | None
   └─ metadata: dict
```

---

#### 2.3.2 文档分块 (`ingestion.py`)

**分块策略**：
```python
def chunk_documents(
    documents: list[IngestDocument],
    *,
    chunk_size_tokens: int,           # 块大小
    chunk_overlap_tokens: int,        # 重叠大小
) -> list[IngestChunk]
```

**处理流程**：

1. **文本文档分块**：
   ```
   tokens = text.split()
   step = chunk_size - chunk_overlap
   for start in range(0, len(tokens), step):
       chunk = tokens[start : start + chunk_size]
       yield IngestChunk(chunk_id=f"{source}:text:{index}")
   ```

2. **页面块直接传递**：
   ```
   for page in pages:
       yield IngestChunk(chunk_id=f"{source}:page:{page_number}")
   ```

**块 ID 格式**：
- 文本块：`{source_id}:text:{chunk_index}`
- 页面块：`{source_id}:page:{page_number}`

---

#### 2.3.3 RAG 网关 (`gateway.py`)

**协议接口**：
```python
class RagGateway(Protocol):
    def ingest_documents(self, documents: list[IngestDocument]) -> IngestResult
    def retrieve_text(self, query: RetrievalQuery) -> RetrievalResult
    def retrieve_visual(self, query: RetrievalQuery) -> RetrievalResult
    def retrieve_fused(self, query: RetrievalQuery) -> RetrievalResult

class IngestResult(BaseModel):
    source_ids: list[str]
    text_chunks: int = 0
    visual_chunks: int = 0
```

---

#### 2.3.4 RAG API 路由 (`api/routes/rag.py`)

**端点**：

| 方法 | 路由 | 功能 | 支持格式 |
|------|------|------|---------|
| POST | `/rag/ingest` | 摄取文档 | IngestDocument |
| POST | `/rag/upload` | 上传并提取 | DOCX, PPTX, PDF, TXT, MD 等 |
| POST | `/rag/retrieve/text` | 检索文本 | RetrievalQuery |
| POST | `/rag/retrieve/visual` | 检索视觉 | RetrievalQuery |
| POST | `/rag/retrieve/fused` | 融合检索 | RetrievalQuery |

**文件格式支持**：
- `.txt/.md/.rst/.html/.csv/.json/.yaml` → 直接解码 UTF-8
- `.docx` → 提取 `word/document.xml`
- `.pptx` → 提取所有 `ppt/slides/slide*.xml`
- `.pdf` → 粗提取可读文本（Latin-1）

---

### 2.4 QQ/OneBot 集成 (`api/routes/qq.py`)

#### 2.4.1 自动化设置

```python
class QqAutomationSettings(BaseModel):
    auto_evaluate_enabled: bool = False
    auto_reply_enabled: bool = False
    deep_review_enabled: bool = True
    progress_report_enabled: bool = True
    progress_report_level: Literal["minimal", "normal", "verbose"] = "minimal"
    onebot_api_base_url: str = "http://127.0.0.1:3001"
    access_token: SecretStr | None = None
    topic_title: str = "QQ 上传课题产物"
    topic_goal: str = "综合评价课题所有产物"
    agent_system_prompt: str = DEFAULT_AGENT_SYSTEM_PROMPT
    blacklist: list[QqBlacklistEntry] = []

class QqBlacklistEntry(BaseModel):
    entry_type: Literal["user", "conversation"]
    value: str
    reason: str | None = None
```

---

#### 2.4.2 事件处理流程

**Webhook 流程**：
```
POST /qq/onebot/webhook
  ↓
OneBotEvent → NormalizedChannelEvent
  ↓
检查是否触发自动评价
  ↓
_run_auto_actions()
  ├─ 检查黑名单
  ├─ 检查群聊触发词
  ├─ 提取压缩包
  ├─ 评价产物
  ├─ 可选：发送进度汇报
  └─ 可选：发送自动回复
```

**触发条件** (`_group_message_should_trigger`)：
1. @机器人 (`self_id` in text)
2. 包含压缩包附件
3. 包含触发词：课题、评价、评测、分析、报告、论文、项目、仓库
4. 包含 URL（HTTP(S))

---

#### 2.4.3 自动评价流程

**路径 1：压缩包评价**
```
压缩包下载 
  ↓
解压验证
  ↓
安全检查
  ↓
文件解析（识别产物类型）
  ↓
规则评价（ProjectEvaluationService）
  ↓
可选 AI 深评（LLM）
  ↓
QQ 回复
```

**路径 2：GitHub 链接深度评价**
```
文本中提取 URL
  ↓
规则评价
  ↓
如果启用深度审查 + LLM 可用 + github.com：
  AI 工具循环（代码审查）
    └─ 克隆、列表、读取、评审
  ↓
更新历史记录
  ↓
QQ 回复
```

**路径 3：普通文本评价**
```
提取文本
  ↓
规则评价
  ↓
可选 AI 深评
  ↓
QQ 回复
```

---

#### 2.4.4 回调机制

**进度汇报** (`_build_progress_callback`):
```python
# 限制报告数量：
# - minimal: 1 条
# - normal: 3 条
# - verbose: 10 条

def callback(message: str) -> None:
    if sent_count >= max_reports:
        return
    sent_count += 1
    _send_auto_reply(normalized, message, settings)
```

**工具日志** (`_build_tool_log_callback`):
```python
# 记录每个工具调用

def callback(tool: str, arguments: dict, result: dict) -> None:
    entry = QqToolLogEntry(...)
    _tool_logs.append(entry.model_dump())
    del _tool_logs[:-500]  # 维持最多 500 条
```

**RAG 检索** (`_build_rag_callback`):
```python
# 在代码审查时支持检索参考资料

def callback(query: str) -> list[dict]:
    result = rag_gateway.retrieve_fused(
        RetrievalQuery(query=query, text_top_k=8, visual_top_k=4)
    )
    return [item.model_dump() for item in result.evidence[:8]]
```

---

#### 2.4.5 LLM 整合

**AI 复述引擎** (`_build_llm_review`):
```
规则评价结果 
  ↓
构建系统提示词 + 用户提示词
  ↓
调用 LLM（temperature=0.2, max_tokens=1200）
  ↓
截断为 4000 字
  ↓
QQ 回复
```

**系统提示词内容** (`DEFAULT_AGENT_SYSTEM_PROMPT`):
- 自我介绍：QQ 课题产物评价智能体
- 能力清单：克隆仓库、列文件、读文件、解压包、进度汇报
- 行为要求：
  - 基于真实工具结果，不编造
  - 像代码审查专家一样逐步查看
  - 关注产物间的证据链
  - 进度汇报自然、简短
  - 最终评价包含：完成度、证据、不足、代码质量、可复现性、建议

---

#### 2.4.6 WebSocket 连接管理

**端点**：
```
POST /qq/ws/connect         # 启动后台 WebSocket 监听
POST /qq/ws/disconnect      # 断开连接
GET  /qq/ws/status          # 获取连接状态
```

**监听器状态**：
```python
class WsListenerStatus(BaseModel):
    state: WsConnectionState        # CONNECTED, CONNECTING, RECONNECTING, DISCONNECTED
    url: str
    reconnect_attempts: int
    last_event_time: datetime | None
    total_events_received: int
```

---

## 3. 完整的评价流程示例

### 3.1 压缩包流程

```
1. QQ 用户上传 project.zip
   ↓
2. OneBotWebhook → _run_auto_actions()
   ↓
3. 下载压缩包到 data/qq-downloads/
   ↓
4. ArchiveInspector.extract_safe() 解压到 data/qq-extracted/
   ↓
5. 安全检查（检查风险文件）
   ↓
6. [可选] 发送进度汇报："已解压，正在分析..."
   ↓
7. 从提取的文件识别产物类型
   - 查找 *.pdf, *.pptx, *.docx → PRESENTATION/PAPER
   - 查找 README, *.py, *.ts → CODE_REPOSITORY
   - 查找 *.md → REPORT
   - 查找 video*, *.mp4, *.srt → VIDEO
   ↓
8. ProjectEvaluationService.evaluate()
   规则评价：
   ├─ 计算每个产物的词数
   ├─ 检测证据信号（是否含实验、复现、风险信息）
   ├─ 按 8 个维度检查关键词
   ├─ 计算加权总分
   └─ 收集优势、不足、建议
   ↓
9. [可选] 如果 deep_review_enabled + LLM 可用：
   调用 LLM 生成友好的复述版本
   ↓
10. 格式化回复
    ├─ 规则评价回复：最多 500 字
    └─ AI 回复：最多 4000 字
   ↓
11. 发送到 QQ
```

### 3.2 GitHub 链接流程

```
1. QQ 用户发送："请评价 https://github.com/user/project"
   ↓
2. OneBotWebhook 触发 _run_auto_actions()
   ↓
3. 检测到 github.com URL
   ↓
4. 快速规则评价（RepositoryAnalyzer）
   ├─ 克隆仓库（浅克隆，深度 1）
   ├─ 列出文件
   ├─ 提取重要文件、测试、CI 等信息
   └─ 预生成 evaluation 结果
   ↓
5. [可选] 如果 deep_review_enabled + LLM 可用 + github.com：
   ↓
6. AgenticRepositoryReviewer.review_url() 启动 AI 工具循环
   ├─ 创建临时工作区
   ├─ AI 循环（最多 40 次）：
   │  ├─ clone_repository
   │  ├─ list_files
   │  ├─ read_file（重要文件、关键代码）
   │  ├─ 可选 retrieve_rag（检索参考资料）
   │  ├─ get_review_history（查看历史评价）
   │  ├─ 可选 send_progress（进度汇报）
   │  ├─ update_review_history（更新历史）
   │  └─ final_answer（最终评价）
   ├─ 清理临时工作区
   └─ 生成 AgenticRepositoryReview
   ↓
7. 每个工具调用触发 tool_log_callback
   └─ 记录到 _tool_logs
   ↓
8. 可选进度回调发送 QQ 消息
   ↓
9. AI 返回最终评价（最多 4000 字）
   ↓
10. 发送到 QQ
```

---

## 4. 数据流与架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                    QQ/OneBot 事件                                │
│                  (压缩包、URL、文本)                            │
└────────────────────────────┬──────────────────────────────────────┘
                             │
                             ▼
                ┌────────────────────────┐
                │  OneBotWebhookResult   │
                │ - archive_inspections  │
                │ - auto_actions         │
                └────────┬───────────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
         ▼               ▼               ▼
    ┌─────────┐  ┌────────────┐  ┌──────────────┐
    │ 压缩包   │  │ GitHub URL  │  │ 普通文本     │
    │ 评价    │  │ 深度审查    │  │ 评价        │
    │         │  │ (工具循环)   │  │             │
    └────┬────┘  └─────┬──────┘  └──────┬───────┘
         │             │                │
         ▼             ▼                ▼
    ┌─────────────────────────────────────────────┐
    │   ProjectEvaluationService.evaluate()       │
    │   规则评价：                                │
    │   ├─ 产物分析 → 类型覆盖率                 │
    │   ├─ 关键词匹配 → 8 维度得分              │
    │   ├─ 缺失检查 → 减分                      │
    │   └─ 加权聚合 → 0-100 总分               │
    │   返回：ProjectEvaluationResult            │
    └──────────────────┬──────────────────────────┘
                       │
         ┌─────────────┴─────────────┐
         │                           │
         ▼ (deep_review_enabled)     ▼ (无 LLM)
    ┌─────────────────┐         ┌──────────────┐
    │ _build_llm_review()      │ 规则结果直接 │
    │ LLM 深度复述    │         │ 格式化回复  │
    │ - 生成文案      │         │            │
    │ - QQ 友好      │         │            │
    └────────┬────────┘         └──────┬──────┘
             │                         │
             └──────────────┬──────────┘
                            │
                            ▼
                     ┌─────────────┐
                     │ QQ 自动回复 │
                     │ (最多 4000字)│
                     └─────────────┘
```

---

## 5. 关键交互点总结

| 交互点 | 调用方 | 被调用方 | 作用 | 位置 |
|--------|--------|---------|------|------|
| `tool_log_callback` | repository_agent.py | qq.py | 记录工具调用 | `_execute_tool()` |
| `progress_callback` | repository_agent.py | qq.py | 发送进度汇报 | `_tool_send_progress()` |
| `rag_callback` | repository_agent.py | qq.py | 检索参考资料 | `_tool_retrieve_rag()` |
| `_build_llm_review()` | qq.py | chat_client | 生成评论 | `_evaluate_text_for_auto_reply()` |
| `_send_auto_reply()` | qq.py | onebot_client | 发送消息 | 多处 |
| `RagGateway.retrieve_fused()` | qq.py | rag_impl | 融合检索 | `_build_rag_callback()` |
| `ReviewHistoryStore.update()` | repository_agent.py | history.py | 记录历史 | `_tool_update_review_history()` |

---

## 6. 部署与配置

### 6.1 环境变量
```bash
ONEBOT_ACCESS_TOKEN=<token>         # OneBot 访问令牌
```

### 6.2 配置端点
```
GET  /qq/automation/settings         # 获取当前设置
PUT  /qq/automation/settings         # 更新设置
```

### 6.3 默认工作目录
```
data/repository-workspaces/         # 仓库分析工作区（RepositoryAnalyzer）
data/repository-agent-workspaces/   # 智能体工作区（AgenticRepositoryReviewer）
data/qq-downloads/                  # QQ 下载文件
data/qq-extracted/                  # 解压文件
data/rag-uploads/                   # RAG 上传文件
data/review-history/                # 评价历史 XLSX
```

---

## 7. 性能与限制

### 7.1 评价服务
- ⏱️ 关键词匹配：O(n·m)，n=产物数，m=关键词数
- ⚡ 速度：通常 < 1s

### 7.2 仓库分析器
- ⌛ 克隆超时：60s
- 📂 最多文件：600
- 📄 最多预览字符：60KB

### 7.3 智能体审查
- 🔄 工具调用：最多 40 次
- 📁 检查文件：最多 80 个
- 📑 单文件：最多 12KB
- 📊 总字符数：最多 180KB
- ⌛ 克隆超时：90s

### 7.4 工具日志
- 💾 最多保留：500 条
- 🔄 日志回滚：自动删除最旧的（FIFO）

### 7.5 QQ 回复
- 📝 规则评价回复：最多 500 字
- 📝 AI 评价回复：最多 4000 字
- 📝 进度汇报：最多 220 字
- 📨 进度报告限制：minimal=1, normal=3, verbose=10

---

## 8. 扩展点

### 8.1 新增评分维度
```python
# 在 DEFAULT_RUBRIC 中添加
RubricCriterion(
    criterion_id="new_dimension",
    name="新维度名",
    description="...",
    weight=0.XX,
)

# 在 KEYWORDS 中添加关键词
KEYWORDS["new_dimension"] = ["keyword1", "keyword2", ...]

# 在 SUGGESTIONS 中添加建议
SUGGESTIONS["new_dimension"] = "补充...建议。"
```

### 8.2 新增产物类型
```python
# 在 ArtifactKind 中添加
class ArtifactKind(StrEnum):
    NEW_TYPE = "new_type"

# 在评价逻辑中处理
EXPECTED_KINDS[ArtifactKind.NEW_TYPE] = "新产物类型标签"
```

### 8.3 新增工具
```python
# 在 AgenticRepositoryReviewer._execute_tool() 中
elif tool == "new_tool":
    result = self._tool_new_tool(arguments, ...)
```

### 8.4 自定义评价规则
```python
class CustomEvaluationService(ProjectEvaluationService):
    def evaluate(self, request: ProjectEvaluationRequest) -> ProjectEvaluationResult:
        # 自定义逻辑
        pass
```

---

## 📚 相关文件速查

| 功能 | 文件 | 关键类/函数 |
|------|------|-----------|
| 规则评价 | `evaluation/service.py` | `ProjectEvaluationService.evaluate()` |
| 数据模型 | `evaluation/models.py` | `ArtifactInput`, `ProjectEvaluationResult` |
| 仓库分析 | `evaluation/repository.py` | `RepositoryAnalyzer.analyze_url()` |
| AI 工具循环 | `evaluation/repository_agent.py` | `AgenticRepositoryReviewer.review_url()` |
| 评价历史 | `evaluation/history.py` | `ReviewHistoryStore.update()` |
| 日志系统 | `api/routes/qq.py` | `QqToolLogEntry`, `_build_tool_log_callback()` |
| RAG 模型 | `rag/models.py` | `IngestDocument`, `RetrievalQuery` |
| 文档分块 | `rag/ingestion.py` | `chunk_documents()` |
| RAG 路由 | `api/routes/rag.py` | `/rag/ingest`, `/rag/retrieve/*` |
| QQ 集成 | `api/routes/qq.py` | `receive_onebot_event()`, `_run_auto_actions()` |

---

**文档完成于**：2026-05-21  
**分析范围**：breadth="very thorough"  
**包含内容**：评价系统、工具日志、RAG 摄取系统、完整流程

