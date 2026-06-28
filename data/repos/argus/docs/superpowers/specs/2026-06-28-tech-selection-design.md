# Argus 技术选型与模块化接口设计

> 日期：2026-06-28 | 状态：待实施 | 对应架构：docs/architecture.html (13 张图)

---

## 一、技术选型总览

### 1.1 最终选型表（MVP）

| 层 | 选型 | 说明 |
|----|------|------|
| 语言 | Python 3.12+ (asyncio) | IO 密集型，async 足够；全团队统一 |
| LLM SDK | `openai` | 兼容 DeepSeek API，未来切换其他 OpenAI-compatible 模型 |
| Agent 编排 | 自研 tool-use loop | 流程明确（两阶段分析），< 500 行，不值得引入框架 |
| Web 框架 | FastAPI + Pydantic v2 | async-native，自动 OpenAPI，接入团队友好 |
| 数据库 | PostgreSQL 16 | 核心业务数据：events / rca_results / owner_mappings / configs / feedbacks |
| 向量库(可选) | pgvector（PG 扩展） | 复用 PG，历史案例 RAG；MVP 可关闭 |
| 缓存/限流 | Redis 7 | 指纹缓存 / 限流计数 / 去重状态 / 静默期 TTL |
| 任务队列(MVP) | arq (Redis-based) | 避免引入 Kafka，复用 Redis；P2 换 Kafka 时分区分级 |
| 代码检索 | gitpython + tree-sitter-py | git grep（精确）+ tree-sitter AST（结构），多语言支持 |
| 邮件通知 | aiosmtplib + Jinja2 | async SMTP，HTML 模板渲染 diff |
| IM 通知 | httpx → webhook | 企微 / 钉钉 / Slack 统一 webhook 协议 |
| 日志 | structlog | 结构化 JSON，事件 ID 贯穿全链路 |
| 指标 | prometheus-client | Prometheus 拉模式 |
| 追踪 | opentelemetry-sdk | OTLP exporter，可选 |
| 配置 | YAML + Pydantic Settings | 文件配置 + 环境变量覆盖，Pydantic 验证 |
| 部署 | Docker Compose | Docker Desktop 已就绪，本地开发 + MVP 部署 |

### 1.2 LLM 模型策略

| 用途 | 模型 | 说明 |
|------|------|------|
| 根因分类（粗筛） | deepseek-chat | 便宜，频繁调用 |
| 根因分析 + 方案生成 | deepseek-chat / deepseek-reasoner | 核心能力 |
| 代码片段理解 | deepseek-chat | 长上下文 |
| 未来备选 | 任意 OpenAI-compatible | 改 base_url + api_key 即切换 |

### 1.3 选型原则

1. **MVP 优先复用** — arq 复用 Redis，pgvector 复用 PG，减少独立服务
2. **渐进升级** — 每个组件有明确的 P1/P2 升级路径（arq→Kafka, pgvector→Milvus）
3. **接口隔离** — 换一个模块不影响其他模块（见第二节）
4. **无强制依赖** — 向量库、IM通知、OTel 追踪全部可选，关闭不报错

---

## 二、模块化接口设计

### 2.1 设计原则

- 每个模块定义 **Protocol**（`typing.Protocol`），运行时通过配置注入具体实现
- 业务逻辑只依赖 Protocol，永远不 `import` 具体实现
- 新增替代实现 = 实现 Protocol + 注册到配置
- 即插即用：关闭一个功能不报错（如不配 IM webhook → 只发邮件）

### 2.2 核心接口定义

#### LLMClient — LLM 调用

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class LLMClient(Protocol):
    """LLM 调用抽象 — 换模型只改配置不改代码"""

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.1,          # 根因分析低温度
    ) -> str: ...

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]: ...
```

| 内置实现 | 说明 |
|----------|------|
| `OpenAILLMClient` | 默认。base_url 指向 DeepSeek，改 url+key 切 Claude/GPT |
| `OllamaLLMClient` | 私有部署。base_url → localhost:11434 |

#### Notifier — 通知渠道

```python
from dataclasses import dataclass

@dataclass
class Notification:
    subject: str
    body_html: str
    body_text: str
    recipients: list[str]          # 邮箱或 IM 用户 ID
    priority: str                  # P0/P1/P2/P3

class Notifier(Protocol):
    """通知渠道抽象 — 可同时注入多个实现（邮件+IM）"""

    @property
    def channel_name(self) -> str: ...    # "smtp" / "wecom_webhook" / "slack"

    async def send(self, notification: Notification) -> bool: ...
```

| 内置实现 | 说明 |
|----------|------|
| `SMTPNotifier` | aiosmtplib + Jinja2 HTML 模板，diff 渲染 |
| `WeComWebhookNotifier` | 企微机器人 webhook，@负责人 |
| `DingTalkWebhookNotifier` | 钉钉 webhook |
| `SlackWebhookNotifier` | Slack Incoming Webhook |
| `LogNotifier` | 开发调试用，stdout 打印（不发送） |

#### LogSource — 日志源接入

```python
@dataclass
class RawEvent:
    source: str                     # "sentry" / "elk" / "loki" / "tail"
    timestamp: str                  # ISO 8601
    raw_message: str
    stack_trace: str | None
    service_name: str
    host: str
    environment: str                # prod / staging / dev
    metadata: dict[str, object]     # 源特定字段

class LogSource(Protocol):
    """日志源抽象 — 新增来源实现此接口即可"""

    @property
    def source_name(self) -> str: ...

    async def listen(self) -> AsyncIterator[RawEvent]: ...
    async def ack(self, event_id: str) -> None: ...
```

| 内置实现 | 说明 |
|----------|------|
| `SentryWebhookSource` | FastAPI endpoint 接收 Sentry webhook |
| `ELKSubscriptionSource` | ES query 订阅，定时拉取 |
| `FileTailSource` | aiofiles tail 日志文件 |
| `APMWebhookSource` | Datadog / NewRelic webhook |
| `StdinSource` | 开发调试用，stdin 读 JSON lines |

#### EventBus — 事件队列

```python
@dataclass
class AnomalyEvent:
    event_id: str
    fingerprint: str
    raw_sample: RawEvent
    count: int
    priority: str                  # P0/P1/P2/P3
    first_seen: str
    last_seen: str

class EventBus(Protocol):
    """事件队列抽象 — arq(Redis) vs Kafka 对外接口一致"""

    async def publish(self, event: AnomalyEvent, priority: str) -> str: ...
    async def consume(self, priority: str) -> AsyncIterator[AnomalyEvent]: ...
    async def dead_letter(self, event: AnomalyEvent, reason: str) -> None: ...
```

| 内置实现 | 说明 |
|----------|------|
| `RedisEventBus` | MVP。arq + Redis Streams，按 priority 分 stream |
| `KafkaEventBus` | P2。按 priority 分 partition，持久化更强 |

#### CodeSearcher — 代码检索

```python
from dataclasses import dataclass

@dataclass
class CodeHit:
    file_path: str
    line_number: int
    content: str
    context: list[str]             # 前后 N 行

@dataclass
class CallGraphNode:
    function_name: str
    file_path: str
    line_number: int
    callers: list[str]
    callees: list[str]

class CodeSearcher(Protocol):
    """代码检索抽象 — grep + AST 统一接口"""

    async def grep(
        self, repo: str, pattern: str, *, commit: str, glob: str | None = None,
    ) -> list[CodeHit]: ...

    async def find_definition(
        self, repo: str, symbol: str, *, commit: str,
    ) -> CodeHit | None: ...

    async def get_call_graph(
        self, repo: str, function: str, *, commit: str, depth: int = 2,
    ) -> CallGraphNode | None: ...

    async def blame(
        self, repo: str, file_path: str, line_number: int, *, commit: str,
    ) -> tuple[str, str]: ...     # (author_email, commit_sha)
```

| 内置实现 | 说明 |
|----------|------|
| `LocalRepoCodeSearcher` | git grep + gitpython blame + tree-sitter AST |
| `SourcegraphCodeSearcher` | 企业已有 Sourcegraph 时用 API |
| `NoopCodeSearcher` | 测试用，返回空结果 |

#### ASTIndexer — AST 索引

```python
@dataclass
class ASTIndex:
    repo: str
    commit: str
    symbols: dict[str, CodeHit]    # 符号名 → 位置
    call_graph: dict[str, list[str]]  # 函数 → 调用者列表

class ASTIndexer(Protocol):
    """AST 索引抽象 — tree-sitter vs LSIF 对外一致"""

    async def build_index(self, repo_path: str, commit: str, languages: list[str]) -> ASTIndex: ...
    async def incremental_update(self, repo_path: str, changed_files: list[str]) -> None: ...
```

| 内置实现 | 说明 |
|----------|------|
| `TreeSitterIndexer` | 主力。tree-sitter 多语言 AST |
| `LSIFIndexer` | 已有 LSIF/Scip 索引时读取 |
| `NoopIndexer` | 无 AST 能力时退化（仅 grep） |

#### VectorStore — 向量库（可选）

```python
@dataclass
class VectorDoc:
    id: str
    text: str
    metadata: dict[str, object]
    embedding: list[float] | None   # None 时服务端自动向量化

class VectorStore(Protocol):
    """向量库抽象 — pgvector vs Milvus 对外一致"""

    async def store(self, docs: list[VectorDoc]) -> list[str]: ...
    async def search(self, query: str, *, top_k: int = 5) -> list[tuple[VectorDoc, float]]: ...
    async def delete(self, doc_id: str) -> None: ...
```

| 内置实现 | 说明 |
|----------|------|
| `PgVectorStore` | 默认（可选）。pgvector 扩展，复用 PG |
| `MilvusVectorStore` | P2。大规模历史案例 |
| `NoopVectorStore` | 关闭向量库时不报错 |

#### OwnerResolver — 责任人解析

```python
@dataclass
class OwnerResult:
    name: str
    email: str
    im_id: str | None              # 企微/钉钉 ID
    source: str                    # "codeowners" / "owner_file" / "blame" / "readme"
    confidence: float              # 0.0-1.0

class OwnerResolver(Protocol):
    """定责抽象 — 四级 fallback 统一接口"""

    async def resolve(
        self, repo: str, file_path: str, line_number: int, *, commit: str,
    ) -> list[OwnerResult]: ...
```

| 内置实现 | 说明 |
|----------|------|
| `GitHubOwnerResolver` | CODEOWNERS → OWNER 文件 → blame → README 四级 fallback |
| `PagerDutyResolver` | 已有 PagerDuty oncall 排班时使用 |
| `StaticOwnerResolver` | 配置文件静态映射（MVP 调试用） |

#### Fingerprinter — 指纹算法

```python
@dataclass
class Fingerprint:
    hash: str
    exception_type: str
    template_message: str
    top_frames: list[str]          # stack top-N 帧归一化后

class Fingerprinter(Protocol):
    """指纹聚合抽象 — 算法可插拔、可调参"""

    def fingerprint(self, event: RawEvent) -> Fingerprint: ...
    def is_same_group(self, fp1: Fingerprint, fp2: Fingerprint) -> bool: ...
```

| 内置实现 | 说明 |
|----------|------|
| `StackMessageFingerprinter` | 默认。stack top-N + exception_type + message 模板 hash |
| `SemanticFingerprinter` | P1。embedding 相似度聚类（需向量库） |

---

## 三、配置驱动的模块加载

### 3.1 配置结构

```yaml
# config.yaml
app:
  name: argus
  environment: dev              # dev / staging / prod

llm:
  provider: openai              # openai / ollama / custom
  base_url: https://api.deepseek.com
  api_key: ${DEEPSEEK_API_KEY}  # 环境变量引用
  models:
    cheap: deepseek-chat
    strong: deepseek-chat
    reasoning: deepseek-reasoner
  limits:
    daily_token_budget: 10000000
    max_concurrency: 5

event_bus:
  provider: redis               # redis / kafka
  redis:
    url: redis://localhost:6379/0
    streams:
      p0: argus:events:p0
      p1: argus:events:p1
      p2: argus:events:p2

code_search:
  provider: local               # local / sourcegraph / noop
  local:
    repos_root: ./data/repos
    languages: [python, java, go, typescript]
  ast_indexer: treesitter       # treesitter / lsif / noop

notifiers:
  - type: smtp                  # 可以配多个，同时生效
    host: smtp.company.com
    port: 587
    username: ${SMTP_USER}
    password: ${SMTP_PASS}
  - type: wecom_webhook
    url: ${WECOM_WEBHOOK_URL}
  # - type: slack_webhook        # 加一行就多一个通知渠道
  #   url: ${SLACK_WEBHOOK_URL}

log_sources:
  - type: sentry_webhook
    endpoint: /hooks/sentry
  - type: file_tail
    path: /var/log/app/*.log

vector_store:
  provider: noop                # noop / pgvector / milvus
  # pgvector:
  #   conn_string: postgresql://...

owner_resolver:
  provider: github              # github / pagerduty / static
  fallback_chain:
    - codeowners
    - owner_file
    - blame
    - readme

fingerprinter:
  provider: stack_message       # stack_message / semantic
  stack_top_n: 5
  normalization:
    number_pattern: '\d+'
    uuid_pattern: '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
```

### 3.2 依赖注入容器

```python
# argus/di.py — 简单依赖注入
import yaml
from argus.interfaces import LLMClient, Notifier, EventBus, CodeSearcher, ...

_registry: dict[type, object] = {}

def register(proto: type, impl: object) -> None:
    _registry[proto] = impl

def get(proto: type[T]) -> T:
    return _registry[proto]

def load_config(path: str) -> dict:
    """加载 YAML 配置 + 环境变量替换"""
    ...

def bootstrap(config: dict) -> None:
    """根据配置实例化所有实现并注册"""
    if config["llm"]["provider"] == "openai":
        register(LLMClient, OpenAILLMClient(config["llm"]))
    elif config["llm"]["provider"] == "ollama":
        register(LLMClient, OllamaLLMClient(config["llm"]))

    notifiers = [_create_notifier(n) for n in config["notifiers"]]
    register(list[Notifier], notifiers)   # 多 notifier 注入

    # ... 其余模块同理
```

---

## 四、项目目录结构

```
Argus/
├── argus/                          # 主包
│   ├── __init__.py
│   ├── interfaces/                 # 所有 Protocol 定义
│   │   ├── __init__.py
│   │   ├── llm.py                  # LLMClient Protocol
│   │   ├── notifier.py             # Notifier Protocol
│   │   ├── log_source.py           # LogSource Protocol
│   │   ├── event_bus.py            # EventBus Protocol
│   │   ├── code_search.py          # CodeSearcher + ASTIndexer Protocol
│   │   ├── vector_store.py         # VectorStore Protocol
│   │   ├── owner_resolver.py       # OwnerResolver Protocol
│   │   └── fingerprinter.py       # Fingerprinter Protocol
│   ├── implementations/            # 各接口的具体实现
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   └── openai_client.py    # OpenAILLMClient
│   │   ├── notifiers/
│   │   │   ├── __init__.py
│   │   │   ├── smtp_notifier.py
│   │   │   ├── wecom_notifier.py
│   │   │   └── dingtalk_notifier.py
│   │   ├── log_sources/
│   │   │   ├── sentry_source.py
│   │   │   └── file_tail_source.py
│   │   ├── event_bus/
│   │   │   └── redis_bus.py
│   │   ├── code_search/
│   │   │   ├── local_searcher.py
│   │   │   └── treesitter_indexer.py
│   │   ├── owner/
│   │   │   └── github_resolver.py
│   │   └── fingerprint/
│   │       └── stack_message_fp.py
│   ├── services/                   # 业务逻辑（只依赖 interfaces）
│   │   ├── __init__.py
│   │   ├── ingest.py               # 采集降噪服务
│   │   ├── orchestration.py        # 编排调度服务
│   │   ├── rca_agent.py            # LLM 根因分析 Agent（自研 loop）
│   │   ├── code_retrieval.py       # 代码检索编排
│   │   ├── owner_resolution.py     # 定责编排
│   │   └── notification.py         # 通知编排
│   ├── models/                     # Pydantic 数据模型 + DB schema
│   │   ├── __init__.py
│   │   ├── event.py
│   │   ├── analysis.py
│   │   └── config.py
│   ├── di.py                       # 依赖注入 / bootstrap
│   └── config.py                    # Pydantic Settings，YAML 加载
├── web/                            # FastAPI Web 层
│   ├── __init__.py
│   ├── app.py                      # FastAPI 应用入口
│   ├── routes/
│   │   ├── hooks.py                # Webhook 接收（Sentry 等）
│   │   ├── events.py               # 事件查询 API
│   │   ├── admin.py                # 管理 API（白名单/规则/配置）
│   │   └── health.py               # Health check
│   └── templates/                  # Jinja2 邮件模板
│       ├── notification.html
│       └── diff_block.html
├── config/
│   ├── config.yaml                 # 默认配置
│   ├── config.dev.yaml             # 开发环境覆盖
│   └── config.prod.yaml            # 生产环境覆盖
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── docs/
│   ├── architecture.html           # 已有：13 张架构图
│   ├── implementation-analysis.md  # 已有：实现条件分析
│   ├── superpowers/
│   │   └── specs/
│   │       └── 2026-06-28-tech-selection-design.md  # 本文档
│   └── *.mmd                       # 已有：独立 mermaid 图
├── docker-compose.yml              # 开发环境（PG + Redis + Argus）
├── Dockerfile
├── pyproject.toml                  # 项目元数据 + 依赖
└── README.md
```

---

## 五、MVP 与完整版边界

### 5.1 MVP 交付范围（对应 P0）

| 模块 | MVP 做 | MVP 不做（P1/P2） |
|------|--------|-------------------|
| **采集降噪** | Sentry webhook 接入 + 指纹聚合(StackMessage) + 时间窗去重 + 白名单 | ELK/Loki/file tail、语义指纹 |
| **编排** | Redis arq 队列 + 优先级打分 + 去抖 | Kafka、降级阶梯(先只正常+熔断) |
| **LLM 分析** | OpenAI SDK→DeepSeek + 自研两阶段 agent + 代码/非代码分类 | 多模型路由、语义缓存 |
| **代码检索** | git grep + gitpython blame + tree-sitter AST 索引 | 调用图/数据流图、LSIF、向量语义 |
| **定责通知** | GitHub CODEOWNERS→blame fallback + SMTP 邮件 + Jinja2 diff 渲染 | IM webhook、通知编排(去重/升级/静默) |
| **反馈闭环** | 反馈 API (准确/不准/找错人) + PG 存储 | 知识库 RAG、回灌模型优化 |
| **向量库** | ❌ 不建 | pgvector（P1） |
| **管理 UI** | ❌ 不做 | FastAPI + Jinja2 SSR（P2） |
| **安全脱敏** | 正则脱敏（邮箱/手机/密钥） | NER 脱敏、租户隔离 |
| **可观测性** | structlog + prometheus-client | OTel 追踪（P1） |
| **ADO 支持** | ❌ 不做 | Service Principal 适配（P2） |

### 5.2 MVP 目标

- **1 个日志源**（Sentry webhook）
- **1 种通知渠道**（SMTP 邮件）
- **1 个代码平台**（GitHub）
- **1 个 LLM 模型**（DeepSeek）
- **单服务部署**（Docker Compose，一个容器跑全部）
- **闭环**：Sentry 异常 → 降噪 → LLM 分析（grep+blame） → 邮件通知（根因+diff）→ 反馈记录

---

## 六、Spec 自检清单

- [x] 无 TBD/TODO 占位符
- [x] 每个 Protocol 有对应的内置实现列表
- [x] 配置结构与接口定义一致（provider 字段对应实现类）
- [x] MVP 边界明确（P0 做什么、不做什么）
- [x] 支持关闭可选模块（vector_store: noop、不配 IM webhook）
- [x] 目录结构覆盖所有架构层
- [x] 无内部矛盾（接口名、模块名全文一致）

---

## 七、下一步

本 spec 经 review 确认后，进入 **writing-plans** 阶段，拆分 MVP 实施计划（模块开发顺序、里程碑、任务拆分）。
