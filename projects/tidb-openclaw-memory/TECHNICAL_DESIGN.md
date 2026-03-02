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
- Anchor 存储在本地文件或本地 SQLite
- 适合单机开发、低门槛验证

## 4.2 Hybrid Mode (recommended for prod)
- 本地缓存 latest anchor（低延迟）
- 云端 TiDB 存储权威副本（恢复与一致性）
- 读路径：先本地，后云端回源
- 写路径：本地先写 + 异步写云（可重试）

---

## 5. Data Model (Phase A)

```json
{
  "conversation_id": "string",
  "anchor_version": 12,
  "updated_at": "2026-03-01T03:30:00Z",
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
触发时机：
1. 每 N 轮（建议 N=10）
2. 关键事件（目标变化、结论确认、承诺动作）
3. 每轮回答后（轻量增量）

处理步骤：
1. 取最近窗口对话
2. 结构化抽取（state/facts/intent）
3. 与上一版本合并
4. 生成新 `anchor_version`
5. 写入 local store
6. （hybrid）异步写 TiDB

## 6.2 Read Path (Pre-Response Recovery)
每次回答前：
1. 读取 latest anchor（内存缓存 -> 本地存储 -> 云端回源）
2. 构建 `continuity_context_block`
3. 与当前 user query 组合后送模型

## 6.3 Response Path
1. 模型基于 continuity block + 当前提问作答
2. 输出后触发 anchor 增量更新
3. 记录连续性指标（成功/漂移/冲突）

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
- 云端异步重试（指数退避）

## 8.4 Read Timeout
- 超过阈值直接走本地缓存
- 20s 内必须返回可用结果

---

## 9. Performance Design
1. latest anchor 内存缓存（conversation_id key）
2. anchor payload 控制（建议 <= 2KB 文本化块）
3. 增量更新，避免每轮全量重算
4. 异步云写，避免阻塞回答链路

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

---

## 12. Security & Data Boundary
- 本地模式：数据不出机
- hybrid 模式：仅上传 anchor 结构化摘要，不上传全量原文（可配置）
- conversation_id 做租户隔离前缀
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
