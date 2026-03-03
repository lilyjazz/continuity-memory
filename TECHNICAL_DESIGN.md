# Technical Design v0.1 — Phase A (No-Fork) Conversation Continuity Anchor

## 0. Purpose
本文档定义 P0/P0.5 的 **Phase A 最小可行技术方案**：
在不改 OpenClaw 核心代码（no-fork, minimal-intrusion）的前提下，解决 context compaction 后会话连续性丢失问题。

---

## 1. Design Goals
1. **Continuity-first**：compaction 后任意后续问题尽量保持上下文连续。
2. **No-fork first**：不要求用户使用 OpenClaw 特殊 fork。
3. **Low latency**：回答链路额外延迟可控（目标 P95 <= 1s）。
4. **Progressive architecture**：支持从 local-only 平滑升级到 hybrid（本地+云）。

---

## 2. Non-Goals (Phase A)
1. 不重构 OpenClaw 的 compaction 内核机制。
2. 不实现完整 long-term memory governance 平台。
3. 不引入复杂权限体系（RBAC/SSO）。
4. 不做跨模态事实抽取。

---

## 3. System Boundary (Critical)

## 3.1 OpenClaw Boundary (外部系统)
OpenClaw 仍负责：
- 会话管理、上下文压缩、模型调用、工具编排
- 原有 channel / provider / session 生命周期

Phase A 不修改其核心 compaction 算法与上下文裁剪逻辑。

## 3.2 Continuity Module Boundary (本项目)
本项目新增“连续性协同层”负责：
- 生成/更新 Continuity Anchor
- 回答前读取 Anchor 并组装 Continuity Context Block
- 回答后增量回写 Anchor
- 指标采集与可观测

一句话：
**OpenClaw 继续做“对话引擎”，Continuity Module 做“对话连续性保险丝”。**

---

## 4. Deployment Modes

## 4.1 Local Mode (default for dev)
- Anchor 存储在本地 JSON 版本文件（`FileAnchorStore`）
- 适合单机开发、低门槛验证

## 4.2 Hybrid Mode (recommended for prod)
- 本地版本文件作为主读写路径（低延迟）
- 云端 TiDB Zero 作为远端副本（恢复与跨实例兜底）
- 读路径：本地 latest -> 本地 previous（损坏回退）-> 云端回源
- 写路径：本地先写；远端失败进入 `pending_retry` 队列，后续 `flush_retry` 补偿

## 4.3 OpenClaw Plugin Mode (no-fork default integration)
- 通过 OpenClaw 插件 hooks 进行默认接入，不改 OpenClaw core
- hooks: `before_agent_start`, `before_compaction`, `before_reset`, `agent_end`
- 插件通过 HTTP API 访问 continuity 服务：`/anchor/update`, `/anchor/render-context`, `/anchor/ack-response`
- 插件骨架位于 `assets/openclaw-continuity-plugin/`

---

## 5. Data Model (Phase A)

```json
{
  "conversation_id": "string",
  "anchor_version": 12,
  "timestamp": 1772510437.0,
  "turn_range": [120, 145],
  "summary_compact": "短摘要",
  "state": {
    "goal": "...",
    "done": ["..."],
    "in_progress": ["..."],
    "blockers": ["..."],
    "next_steps": ["..."],
    "decisions": ["..."]
  },
  "facts": {
    "entities": ["..."],
    "confirmed_facts": ["..."],
    "constraints": ["..."],
    "open_questions": ["..."]
  },
  "intent": {
    "current_intent": "...",
    "topic_stack": ["..."],
    "assistant_commitments": ["..."],
    "recent_user_asks": ["..."]
  },
  "meta": {
    "confidence": 0.87,
    "source_turn_refs": [132, 135, 141],
    "checksum": "sha256:..."
  }
}
```

---

## 6. Core Logic

## 6.1 Write Path (Anchor Update)
触发时机（当前实现）：
1. 每 N 轮（默认 N=10）
2. 关键事件（topic/decision/commitment/conclusion）
3. compaction/reset 前强制刷新
4. 回答后 ack 触发强制刷新

处理步骤：
1. 取最近窗口对话（最多 20 turns）
2. 结构化抽取（state/facts/intent）
3. 与上一版本合并（去重并保留历史关键条目）
4. 生成新 `anchor_version` + checksum
5. 写入 local store
6. （hybrid）尝试写 TiDB，失败则加入 `pending_retry`

## 6.2 Read Path (Pre-Response Recovery)
每次回答前：
1. 读取 latest anchor（本地 latest -> 本地 previous -> 云端回源）
2. 构建 `continuity_context_block`
3. 与当前 user query 组合后送模型
4. 若没有可用 anchor，返回 degrade context（最近 turns 摘要 + 明确重建信号）

## 6.3 Response Path
1. 模型基于 continuity block + 当前提问作答
2. 输出后触发 anchor 增量更新
3. 记录连续性指标（成功/漂移/冲突）

## 6.4 Sequence — Normal Ask (Plugin + API)

```text
User -> OpenClaw Agent: ask(query)
OpenClaw Agent -> Plugin(before_agent_start): hook(event, ctx)
Plugin -> Anchor API: POST /anchor/update (optional lightweight refresh)
Plugin -> Anchor API: POST /anchor/render-context (conversation_id, query)
Anchor API -> Service: render_context()
Service -> Store: read latest (local -> previous -> remote fallback)
Store -> Service: anchor or degrade signal
Service -> Anchor API: continuity_context_block
Anchor API -> Plugin: block
Plugin -> OpenClaw Agent: prependContext(block)
OpenClaw Agent -> Model: prompt + continuity block
Model -> OpenClaw Agent: answer
OpenClaw Agent -> Plugin(agent_end): hook(event, ctx)
Plugin -> Anchor API: POST /anchor/ack-response (response_text, turn_id)
Anchor API -> Service: ack_response()
Service -> Store: update anchor version
Store -> Service: persisted version
Service -> Anchor API -> Plugin -> OpenClaw Agent: ack done
```

## 6.5 Sequence — /compact Path

```text
User -> OpenClaw Agent: /compact
OpenClaw Agent -> Plugin(before_compaction): hook(event, ctx)
Plugin -> Anchor API: POST /anchor/update (force=true, event=before_compaction)
Anchor API -> Service: update_anchor(force)
Service -> Store: write local latest
Service -> Hybrid Remote: try write TiDB Zero
Hybrid Remote -> Service: ok OR fail
Service: on remote fail, enqueue pending_retry
Service -> Anchor API -> Plugin -> OpenClaw Agent: compaction-safe snapshot ready
OpenClaw Agent -> OpenClaw Core: execute compaction
```

## 6.6 Sequence — /reset Path

```text
User -> OpenClaw Agent: /reset (or /new)
OpenClaw Agent -> Plugin(before_reset): hook(event, ctx)
Plugin -> Anchor API: POST /anchor/update (force=true, event=before_reset)
Anchor API -> Service: update_anchor(force)
Service -> Store: write local latest (+ remote best-effort)
OpenClaw Agent -> OpenClaw Core: clear session history
Next user ask -> before_agent_start hook -> render-context
Plugin -> Anchor API: POST /anchor/render-context
Anchor API -> Service -> Store: load anchor from persisted continuity state
Service -> Plugin: continuity_context_block
Plugin -> OpenClaw Agent: prependContext for post-reset continuity
```

## 6.7 Sequence — Degrade / Fallback

```text
Plugin -> Anchor API: POST /anchor/render-context
Anchor API -> Service: render_context()
Service -> Local Store: read latest
Local Store -> Service: missing or corrupted
Service -> Local Store: read previous version
Previous missing -> Service -> Remote Store: fetch latest
Remote missing/unavailable -> Service: produce degrade context block
Service -> Anchor API -> Plugin: degrade context (short summary + rebuild hint)
Plugin -> OpenClaw Agent: continue response path (fail-open)
```

---

## 7. Continuity Context Block Template

```text
[Conversation Continuity Context]
Current Goal: ...
Done: ...
In Progress: ...
Blockers: ...
Next Steps: ...
Confirmed Facts: ...
Current Intent: ...
Constraints: ...
```

注入原则：
- 优先短而准（控制 token）
- 保留事实一致性与当前意图
- 不注入过多历史原文

---

## 8. Failure Handling & Degrade

## 8.1 Anchor Missing
- 使用最近摘要 + 最近关键轮次
- 回复中给出可执行确认问题（重建上下文）

## 8.2 Anchor Corrupted (checksum mismatch)
- 回退到上一版本 anchor
- 触发后台重建任务

## 8.3 Cloud Write Failure (hybrid)
- 本地先成功即不中断回答
- 失败项进入持久化 `pending_retry`，通过后台 retry worker + `flush_retry` 批量补偿

## 8.4 Read Timeout
- 服务配置包含 `read_timeout_seconds`（默认 20s）
- 当前版本未将该阈值强制绑定到存储调用超时控制（后续优化项）

---

## 9. Performance Design
1. 本地文件优先读写，云端仅作为回源与副本
2. anchor payload 控制（短摘要 + 结构化字段）
3. 增量更新，避免每轮全量重算
4. 云写失败不阻塞回答链路（降级到 `pending_retry`）

当前验证补充：
- 真实 EC2 behavioral matrix（compact/reset）已常态化执行
- 已补充 quality dataset + stability loop + nightly gate 脚本

目标：
- 额外 P95 延迟 <= 1s

---

## 10. Observability

Metrics:
- continuity_success_rate
- context_drift_rate
- contradiction_rate
- anchor_write_success_rate
- anchor_read_latency_p95
- degrade_path_rate

Logs:
- anchor_version transition
- source_turn_refs
- degrade reason

Dashboards:
- 按会话/用户/环境查看连续性质量

## 10.1 Observability Sequence (Runtime)

```text
User ask
  -> before_agent_start hook start
  -> /anchor/update (optional refresh)
  -> /anchor/render-context
  -> context injected + model response
  -> /anchor/ack-response
  -> hook end

At each step:
- emit structured log (event name, conversation_id, latency_ms, outcome)
- update counters/ratios for success, degrade, and fallback path
```

## 10.2 Metrics Mapping by Stage

1. before_agent_start / render stage
- `anchor_read_latency_p95`: render-context read path latency (local/previous/remote)
- `degrade_path_rate`: hit when render falls back to degrade block

2. update stage (`/anchor/update`)
- `anchor_write_success_rate`: local write success and hybrid remote write success
- `continuity_success_rate` (leading indicator): expected-context availability before answer

3. answer + ack stage (`/anchor/ack-response`)
- `context_drift_rate`: answer misses expected continuity facts
- `contradiction_rate`: answer conflicts with confirmed facts/constraints

4. hybrid retry stage (`pending_retry` -> `flush_retry`)
- retry queue depth (recommended custom metric)
- retry flush success ratio (recommended custom metric)

## 10.3 Benchmark/Report Metrics (Offline Validation)

Current offline gates are produced by benchmark scripts and written into `reports/*.json`:

- strict deltas: `delta` / `delta_strict`
- semantic deltas: `delta_semantic`
- elapsed time: `elapsed_sec`
- stability: `passed_rounds`, `round_count`, `elapsed_p95_sec`

These outputs are generated by:

- `scripts/run_openclaw_remote_behavioral_ab.py`
- `scripts/run_openclaw_remote_behavioral_reset_ab.py`
- `scripts/run_openclaw_remote_behavioral_matrix.py`
- `scripts/run_openclaw_remote_stability_loop.py`
- `scripts/run_openclaw_remote_nightly_gate.py`

## 10.4 Logging Contract (Recommended)

For each anchor API call and plugin hook, log at least:

- `event`: hook/api event name
- `conversation_id`
- `anchor_version_before` / `anchor_version_after` (if applicable)
- `latency_ms`
- `path`: `local_latest` | `local_previous` | `remote_fallback` | `degrade`
- `outcome`: `ok` | `retry_enqueued` | `degrade` | `error`

This contract keeps online runtime signals and offline benchmark signals joinable by conversation and time window.

---

## 11. API Contract (Internal)

### POST /anchor/update
Input: conversation_id, latest_turns, optional_event
Output: anchor_version, confidence

### GET /anchor/latest?conversation_id=...
Output: latest anchor payload

### POST /anchor/render-context
Input: conversation_id, user_query
Output: continuity_context_block

### POST /anchor/ack-response
Input: conversation_id, response_text, turn_id
Output: updated anchor_version

### GET /metrics
Output: runtime metrics snapshot

### GET /alerts/slo
Output: SLO checks and overall status

---

## 12. Security & Data Boundary
- 本地模式：数据不出机
- hybrid 模式：仅上传 anchor 结构化摘要，不上传全量原文（可配置）
- `/anchor/*` 支持 token 鉴权、租户隔离前缀校验、限流
- conversation_id 使用 `tenant:conversation` 作用域格式
- 云端写入加密传输 + 访问密钥管理

---

## 13. Phase Plan

### Phase A1 (Week 1)
- Local mode complete
- 端到端可跑（update/read/render/ack）

### Phase A2 (Week 2)
- Compaction replay harness
- 指标采集

### Phase A3 (Week 3)
- Hybrid mode with TiDB
- 重试与回源完善

### Phase A4 (Week 4)
- 灰度 + Go/No-Go

---

## 14. Acceptance Criteria
1. compaction 后任意问题连续作答率 >= 95%
2. contradiction_rate <= 2%
3. 有 anchor 时失忆回复率 = 0
4. 额外 P95 延迟 <= 1s
5. 至少 3 组真实回放通过

---

## 15. Why This Is Non-Intrusive
1. 不改 OpenClaw compaction 内核逻辑
2. 不要求 fork OpenClaw
3. 仅在外层增加“回答前连续性上下文组装”能力
4. 可插拔、可灰度、可关闭

后续如需更强一致性，再向上游提标准 lifecycle hooks（before_compaction / before_response）作为 Phase B。
