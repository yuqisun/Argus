# Argus — 日志异常智能修复中台

> 监听生产日志中的 exception/error → LLM 分析对应 repo 代码做语义级根因分析（区分代码 bug 与非代码问题）→ 找到最懂这块代码的人 → 将根因 + 修改方案通知到他 → 加速判定和修复。

**不同于传统 ELK/ITRS 只给数据不给结论**，Argus 把"日志异常 ↔ 源码语义 ↔ 修改方案"打通，送到最懂代码的人手里，是"AI 结对修复助手"而非"问责工具"。

## 核心特性

- **日志异常监听**：接 Sentry webhook / ELK 订阅 / APM error span / 文件 tail，统一格式 + 多行堆栈聚合
- **指纹降噪**：stack top-N 帧 + 异常类型 + message 模板归一化 hash，归并同一类异常；时间窗去重 + 静默期 cooldown + 升级检测
- **LLM 两阶段根因分析**：阶段 1 生成候选根因 → 阶段 2 强制回代码验证/否决，对冲单轮"瞎猜"
- **代码/非代码双分支**：代码 bug 进 repo 检索（grep + codegraph）；非代码（数据/配置/依赖/缺文件/容量）也查代码做交叉验证
- **置信度分流**：高置信自动定责 + 带方案；中置信辅助 triage；低置信仅通知标注 AI 未定位——"宁可不说也不乱说"
- **Owner 四级 fallback**：CODEOWNERS → OWNER 文件 → commit blame（主要贡献者）→ README（LLM 读兜底）
- **通知四要素**：根因摘要 + 修改方案（unified diff 草稿）+ 证据链 + 置信度
- **反馈飞轮**：负责人反馈"根因准不准/方案能不能用"回灌知识库，系统越用越准

## 架构概览

系统分五层，完整架构图见 `docs/architecture.html`（13 张可交互 Mermaid 图）：

```
日志源 → 采集降噪 → 调度编排 → LLM 根因分析 → 定责与通知
         (指纹/去重/    (优先级/限流/   (分类/两阶段/     (owner解析/
          预过滤)        降级/去抖)       代码检索)        通知编排/反馈)
```

## 快速开始

### 前置条件

- Python 3.11+
- Redis（可选，无则降级为内存队列）
- PostgreSQL（可选，反馈记录用）
- LLM API Key（DeepSeek/OpenAI/Claude/vLLM 均可）

### 1. 克隆 & 安装

```bash
git clone git@github.com:yuqisun/Argus.git
cd Argus
pip install -e ".[dev]"
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
```

### 3. 配置 service→repo 映射

编辑 `config/config.yaml`，为你的服务配置 repo：

```yaml
service_repos:
  default:
    repo: argus          # data/repos/ 下的目录名
    commit: HEAD
  payment-service:
    repo: payment
    commit: HEAD
```

将要分析的代码仓库克隆到 `data/repos/` 下：

```bash
mkdir -p data/repos
git clone https://github.com/your-org/your-repo.git data/repos/your-repo
```

### 4. 启动

**方式 A：Docker Compose（推荐，含 Redis + PostgreSQL）**

```bash
docker compose up -d
```

**方式 B：本地直接运行**

```bash
# 先启动 Redis（可选）
redis-server &

# 启动 Argus
uvicorn web.app:app --host 0.0.0.0 --port 8000 --reload
```

### 5. 验证

```bash
# 健康检查
curl http://localhost:8000/health

# 发送测试 Sentry webhook
curl -X POST http://localhost:8000/hooks/sentry \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "test-001",
    "message": "ValueError: invalid input",
    "timestamp": "2026-07-01T10:00:00Z",
    "exception": {
      "values": [{
        "type": "ValueError",
        "value": "invalid input",
        "stacktrace": {
          "frames": [
            {"filename": "app.py", "lineno": 42, "function": "handle"}
          ]
        }
      }]
    },
    "tags": {"level": "error", "environment": "prod", "server_name": "api"}
  }'
```

### 6. 接入 Sentry

在 Sentry 项目设置 → Integrations → Webhooks 中配置：

- **Callback URLs**: `http://your-argus-host:8000/hooks/sentry`
- **Events**: 只勾选 `Issue` 相关事件（避免噪音）

## 配置说明

`config/config.yaml` 核心配置项：

| 配置 | 说明 | 默认值 |
|---|---|---|
| `llm.api_key` | LLM API Key（也支持 `DEEPSEEK_API_KEY` 环境变量） | 空 |
| `llm.base_url` | LLM API 地址（兼容 OpenAI 格式） | `https://api.deepseek.com` |
| `llm.models.strong` | 根因分析用模型 | `deepseek-chat` |
| `redis.url` | Redis 连接（去重/队列/限流） | `redis://localhost:6379/0` |
| `code_search.local.repos_root` | 本地 repo 根目录 | `./data/repos` |
| `service_repos` | 服务名→repo 映射 | `{default: {repo: argus, commit: HEAD}}` |
| `fingerprinter.stack_top_n` | 指纹取 stack top-N 帧 | `5` |
| `fingerprinter.dedup_window_seconds` | 去重窗口 | `300` |
| `fingerprinter.cooldown_seconds` | 静默期 | `3600` |
| `notifiers` | 通知渠道配置（SMTP） | localhost:1025 |

## 项目结构

```
argus/
├── interfaces/          # Protocol 接口层（8 个抽象，业务逻辑只依赖接口）
├── implementations/     # 接口实现
│   ├── code_search/     #   本地 git grep + blame + 调用图
│   ├── event_bus/       #   Redis Streams 事件队列 + DLQ
│   ├── fingerprint/     #   stack+message 指纹算法
│   ├── llm/             #   OpenAI 兼容 LLM 客户端
│   ├── notifiers/       #   SMTP 邮件通知
│   └── owner/           #   GitHub CODEOWNERS + blame 定责
├── models/              # 核心数据模型（RawEvent, AnomalyEvent）
├── services/            # 业务逻辑层
│   ├── ingest.py        #   采集降噪（指纹→去重→过滤→发布）
│   ├── orchestration.py #   调度编排（优先级打分）
│   ├── rca_agent.py     #   LLM 两阶段根因分析
│   └── feedback.py      #   反馈记录
├── config.py            # YAML 配置加载 + 环境变量插值
└── di.py                # 依赖注入容器

web/
├── app.py               # FastAPI 入口 + pipeline 组装
├── routes/
│   ├── health.py        # 健康检查
│   └── hooks.py         # Sentry webhook 接收 + 全管道执行
└── templates/           # 邮件通知模板

config/config.yaml       # 默认配置
docs/                    # 架构图 + 分析文档
tests/                   # 单元测试 + 集成测试
```

## 运行测试

```bash
python -m pytest tests/ -v
```

## 架构设计文档

- `docs/architecture.html` — 13 张交互式 Mermaid 架构图（总体架构/核心数据流/根因分析/定责通知/采集降噪/调度编排/LLM根因分析/部署架构/数据存储/安全脱敏/可观测性/LLM调用管理/接入流程）
- `docs/implementation-analysis.md` — 实现条件、团队收益与人力估算
- `docs/code-review.md` — 代码 review 记录

## 技术栈

| 组件 | 技术 |
|---|---|
| Web 框架 | FastAPI + Uvicorn |
| LLM | OpenAI SDK（兼容 DeepSeek/Claude/vLLM/Ollama） |
| 消息队列 | Redis Streams（按优先级分队列 + DLQ） |
| 数据库 | PostgreSQL（asyncpg）— 反馈记录 |
| 缓存/去重 | Redis（SETNX+TTL 去重 + INCR 计数） |
| 代码检索 | git grep + tree-sitter AST + git blame |
| 邮件 | aiosmtplib + Jinja2 模板 |
| 配置 | YAML + 环境变量插值 |
| 日志 | structlog |
| 监控 | prometheus-client |

## 设计理念

1. **修复助手而非问责工具**：找提交人是为了"他最熟，判定修复最快"，不是追责。通知带的是根因+方案而非罚单。
2. **置信度保护信任**：OpenRCA(ICLR 2025) 证明 LLM 定位代码根因准确率仍低。Argus 用两阶段验证 + 置信度分级，低置信宁可不说也不乱说。
3. **非代码根因也查代码**：缺文件要查路径引用确认外部还是内置，配置变更要查读取点。不只是"只看代码"。
4. **检索非单一 RAG**：grep 精确（主力）+ codegraph 结构（关键）是核心，向量语义/历史 RAG 是可选增强。
5. **通知不能断**：即使 LLM 挂了，至少把"有异常 + 找到的人 + 原始日志"通知出去让人工接手。分析可降级，告警必须高可用。

## License

MIT
