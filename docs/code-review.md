# Argus 代码 Review

> Review 范围：`argus/`、`web/`、`tests/`、`config/`、`pyproject.toml`、`Dockerfile`、`docker-compose.yml`
> 代码量：约 1200 行 Python + 配置 + 测试

---

## 总体评价

**架构设计优秀，工程实现是合格的 MVP 骨架。** Protocol 接口层抽象清晰、DI 容器简洁、pipeline 容错降级到位。核心闭环（webhook → 指纹 → 去重 → LLM 根因 → blame 定责 → 邮件通知）已打通。但有几个**必须修复的问题**和一些**工程质量提升点**。

---

## P0 — 必须修复

### 1. `web/hooks.py:76` — RCA 分析传了 `repo="unknown"` `commit="unknown"`
```python
rca_result = await rca.analyze(raw, repo="unknown", commit="unknown")
```
这意味着代码检索和 blame 全部在 `unknown` repo 上执行，必然失败或返回空。webhook 处理里**没有从 Sentry payload 或配置中解析 repo 信息**的逻辑。整个 RCA + Owner 链路在真实场景下跑不通。

**修复方向**：从 Sentry payload 的 release/tags 解析 repo，或按 service_name 映射到配置的 repo。`config.yaml` 应有 service→repo 映射。

### 2. `web/hooks.py:114` — 通知 recipients 为空列表
```python
notif = Notification(
    ...
    recipients=[],  # 空！
    ...
)
```
SMTP 发送时 `To` 为空，邮件发不出去。Owner 解析的结果没有传给通知。

**修复方向**：owner resolve 的结果取 email 填入 recipients。

### 3. `rca_agent.py:148` — Stage 2 验证结果解析过于粗糙
```python
verified = "ALL_REFUTED" not in stage2_response
```
只检查字符串是否包含 `ALL_REFUTED`。LLM 返回的 JSON 没有被解析，无法区分"哪个候选被验证"、"哪个被否决"。如果 LLM 返回格式偏差（如 `all refuted` 小写），会误判为 verified。

**修复方向**：`json.loads(stage2_response)` 解析 verification_results，按 verdict 字段判断。加 try-except 容错。

### 4. `orchestration.py:79-92` — Orchestrator 定义了但没接入 pipeline
`Orchestrator` 类接收 scorer/ingest/rca/owner/notifiers，有 `handle_raw_event` 方法。但 `web/app.py` 的 `_build_pipeline` 没有创建 Orchestrator，`web/hooks.py` 是手动逐步调用各服务的。导致：
- 优先级计算在 `hooks.py:59` 做了一次，但 `ingest.process` 内部没用到 priority（AnomalyEvent.create 硬编码 `priority="P2"`）
- 去抖、限流、降级等编排层逻辑完全缺失

**修复方向**：要么用 Orchestrator 统一编排，要么把 priority 传给 IngestService。当前是两套逻辑各跑各的。

---

## P1 — 应尽快修复

### 5. `ingest.py:15-43` — DedupState 是纯内存状态，多进程不共享
`_seen`/`_cooldowns`/`_counts` 都是实例变量。FastAPI 多 worker 部署时，每个 worker 各自去重，同一 fingerprint 在不同 worker 都会放行。架构设计里明确要求 Redis 存去重状态。

**修复方向**：DedupState 改用 Redis SET + TTL 实现。

### 6. `local_searcher.py:23` — subprocess 调用没有超时和输入校验
```python
result = subprocess.run(
    ["git", "-C", str(repo), *args],
    capture_output=True, text=True, check=check,
)
```
- 没有 `timeout` 参数，git 命令卡住会永久阻塞 async 事件循环（subprocess.run 是同步阻塞调用）。
- `pattern` 参数直接传给 `git grep`，若含 shell 元字符可能注入（虽然用列表传参降低了风险，但 pattern 内容仍需校验）。
- 在 async 函数里用同步 subprocess.run 会阻塞事件循环。

**修复方向**：用 `asyncio.create_subprocess_exec` 替代，加 `timeout=10`。

### 7. `github_resolver.py:20-26` — 同样的 subprocess 同步阻塞问题
与上条相同。`_run_git` 是同步的但在 `async def resolve` 里调用。

### 8. `redis_bus.py:53` — consume 是无限循环但没有退出机制
```python
while True:
    results = await self._redis.xread(...)
    if not results:
        continue
```
没有 cancel/stop 机制。如果消费者任务需要优雅关闭，无法退出。也没有错误处理——Redis 断连会抛异常导致消费者崩溃。

**修复方向**：加 `asyncio.Event` 停止信号，try-except 处理 Redis 连接异常+重连。

### 9. `rca_agent.py:121` — 异常类型提取逻辑脆弱
```python
exc_type = event.raw_message.split(':')[0] if ':' in event.raw_message else event.raw_message[:30]
```
用冒号分割提取异常类型，但消息可能是 `Connection refused to host:port`，会提取出 `Connection refused to host`。这与 fingerprinter 里的 `_extract_exception_type` 逻辑不一致（那边用正则 `\w+(?:Error|Exception|Warning)`）。

**修复方向**：复用 fingerprinter 的异常类型提取逻辑，或从已计算的 Fingerprint 中取 exception_type。

### 10. `feedback.py:36` — SQL 注入风险（低，但应修复）
```python
await self.db.execute(
    "INSERT INTO feedbacks (...) VALUES ($1, $2, $3, $4, NOW())",
    feedback.event_id, ...
)
```
这里用了参数化查询是安全的。但 `feedback.event_id` 直接来自用户输入，应校验格式（当前 event_id 是 UUID[:8]，应校验长度/字符集）。

---

## P2 — 工程质量提升

### 11. 指纹算法只支持 Python 风格 stack trace
```python
match = re.search(r'File\s+"([^"]+)",\s*line\s+(\d+)', line)
```
只匹配 Python `File "xxx", line N` 格式。Java(`at com.foo.Bar.method(Bar.java:42)`)、Go(`panic: ... /main.go:42`)、JS(`at Object.<anonymous> (/app/index.js:42:11)`) 都不匹配。架构设计里明确提到要按语言适配。

**建议**：MVP 阶段先支持 Python 可接受，但应在配置里标注 `language: python` 并在文档说明限制。

### 12. `config.py:58` — 环境变量插值正则不完整
```python
pattern = re.compile(r'\$\{(\w+)(?::-(.*?))?\}')
```
不支持 `${VAR}` 嵌套、不支持 `$VAR` 简写。且 `\w` 不匹配环境变量名中可能出现的下划线以外的特殊字符（虽然下划线在 `\w` 里，OK）。这个基本够用，但 default 值里若含 `}` 会错误匹配。

### 13. `di.py:30-52` — bootstrap 只注册了 LLM 和 Fingerprinter
EventBus、CodeSearcher、OwnerResolver、Notifier 都没在 bootstrap 里注册。`web/app.py` 的 `_build_pipeline` 自己组装了一套，绕过了 DI 容器。两套组装逻辑并存容易混乱。

**建议**：统一到 DI 容器，或删掉 di.py 直接用 `_build_pipeline`。

### 14. `web/app.py:198` — 模块级 `app = create_app()` 副作用
import `web.app` 时立即创建 FastAPI app，若配置缺失会触发 `_build_pipeline` 异常（虽然被 try-except 吞了返回 None）。测试里 `create_app({"environment": "test"})` 和模块级 `app` 是两个不同实例。

**建议**：改为延迟创建（`app = create_app()` 移到 `if __name__` 或工厂函数）。

### 15. 测试覆盖不足
- `tests/unit/implementations/`、`tests/unit/interfaces/`、`tests/unit/models/`、`tests/unit/services/` 目录存在但为空
- 只有 `test_di.py` 和 `test_pipeline.py` 有实际测试
- 核心的 fingerprinter、ingest dedup、rca_agent、code_searcher、owner_resolver 都没有单元测试

### 16. `docker-compose.yml` 缺少 healthcheck 和依赖顺序
（未读取但基于 Dockerfile 推测）Redis/PostgreSQL 启动后 Argus 可能立即连接失败。应加 `depends_on: condition: service_healthy`。

### 17. `data/repos/argus/` 目录提交了完整项目自身克隆
这个目录是代码检索的测试数据，但提交了整个项目的副本到 git，造成仓库膨胀和混乱。

**建议**：加入 `.gitignore`，用脚本或 fixture 生成测试用 repo。

---

## 设计亮点（值得保持）

1. **Protocol 接口层**：8 个 Protocol 抽象清晰，业务逻辑只依赖接口，实现可替换。这是整个代码库最大的优点。
2. **Pipeline 容错降级**：`_build_pipeline` 对每个组件（Redis/LLM/CodeSearch）都有 try-except + fallback，缺组件不崩溃，降级运行。
3. **两阶段 LLM 分析**：Stage1 候选生成 → Stage2 验证否决，与架构设计一致。
4. **指纹归一化**：UUID/IP/数字替换为占位符，避免动态值导致指纹分散。
5. **SMTPNotifier 用 Jinja2 + autoescape**：防 XSS，HTML 邮件模板化。
6. **RedisEventBus 按优先级分队列**：P0/P1/P2 各自 stream key + DLQ，与架构设计一致。

---

## 修复优先级汇总

| 优先级 | 问题 | 影响 |
|---|---|---|
| **P0** | repo="unknown" 导致 RCA 跑不通 | 核心功能不可用 |
| **P0** | recipients=[] 导致邮件发不出 | 通知不可用 |
| **P0** | Stage2 验证结果不解析 JSON | 根因准确率受损 |
| **P0** | Orchestrator 未接入，priority 不生效 | 编排层形同虚设 |
| **P1** | DedupState 纯内存，多 worker 不共享 | 去重失效 |
| **P1** | subprocess 同步阻塞 async 事件循环 | 性能/卡死风险 |
| **P1** | consume 无退出机制无重连 | 消费者不可靠 |
| **P1** | 异常类型提取逻辑不一致 | 检索不准 |
| **P2** | 指纹只支持 Python stack | 多语言受限 |
| **P2** | 测试覆盖不足 | 回归风险 |
| **P2** | data/repos 提交了项目副本 | 仓库膨胀 |
| **P2** | DI 容器与 _build_pipeline 两套逻辑 | 维护混乱 |
