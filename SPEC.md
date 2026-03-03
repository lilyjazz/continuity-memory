# SPEC v0.2 — OpenClaw Compaction-Safe Conversation Continuity

## 1) Problem
在长对话中触发 context compaction 后，系统会丢失关键上下文，出现“失忆”“答非所问”“与先前结论冲突”。

> 目标不是只回答“进展如何”，而是：**compaction 后，用户问任何后续问题，都能保持上下文连续性。**

---

## 2) Objective
构建 **Conversation Continuity Anchor (CCA)** 机制：
- 在 compaction 前后保留高价值上下文
- 在回答时优先恢复连续性上下文
- 对任意问题类型维持稳定回答能力

---

## 3) Direct Evidence
真实用户会话中出现：
- 前文正常
- 触发 compaction 后
- 用户追问当前主题
- 系统回复“context 被压缩了，不记得之前聊什么”

证据图：`./assets/context-compaction-evidence.jpg`

---

## 4) Scope
### In Scope (P0)
1. CCA 数据结构定义与版本化
2. compaction 前自动生成/刷新 CCA
3. 回答前 CCA 恢复与注入
4. 任意问题的连续性优先回答策略
5. 失败降级（无锚点/锚点损坏）

### Out of Scope (P0)
1. 全量长期记忆治理平台
2. 通用向量检索平台重构
3. 企业级 RBAC/SSO 审计全套
4. 跨模态事实抽取

---

## 5) CCA Data Model (核心)
每个锚点包含：
- `conversation_id`
- `anchor_version`
- `timestamp`
- `turn_range`
- `summary_compact`（2-5 句压缩叙述）

### Layer A — State
- `goal`
- `done[]`
- `in_progress[]`
- `blockers[]`
- `next_steps[]`
- `decisions[]`

### Layer B — Facts
- `entities[]`（人、项目、系统、术语）
- `constraints[]`（不能做/必须做）
- `confirmed_facts[]`（已确认事实）
- `open_questions[]`（待澄清问题）

### Layer C — Intent/Dialogue Thread
- `current_intent`
- `user_ask_history[]`（最近关键提问轨迹）
- `assistant_commitments[]`（承诺动作/待办）
- `topic_stack[]`（主题栈）

### Reliability Meta
- `confidence`
- `source_refs[]`（引用轮次）
- `checksum`

---

## 6) Trigger & Lifecycle
1. **Periodic**：每 8~12 轮更新
2. **Threshold**：token 接近 compaction 阈值时强制刷新
3. **Event-based**：检测到主题切换、结论确认、行动承诺时立即刷新
4. **Compaction-hook**：compaction 前必须写入 latest CCA

保留策略：
- 保留最近 N 个版本（建议 N=5）
- latest 常驻缓存

---

## 7) Read/Answer Flow
1. 接收用户问题（不限类型）
2. 拉取 latest CCA（优先本地缓存）
3. 进行问题意图识别 + CCA 对齐
4. 组装“连续性上下文块”注入回答
5. 输出回答并记录是否发生偏移

降级：
- 无 CCA：回退到最近摘要 + 最近关键轮次
- 仍失败：明确“上下文不足，正在重建”，并给出可执行追问

---

## 8) Storage Modes
- `local`：本地持久化（开发模式）
- `hybrid`：本地缓存 + 云端 TiDB（生产推荐）

说明：TiDB 在 P0 的作用是“跨实例连续性保险丝”，不是全量 memory 平台替代。

当前实现补充：
- `local` 当前实现为本地 JSON 版本文件（`FileAnchorStore`）
- `hybrid` 当前实现为 `FileAnchorStore + TiDBZeroRemoteBackend`
- hybrid 失败写入进入持久化 `pending_retry` 队列，支持后台 worker + `flush_retry` 补偿

P0 安全与运维补充：
- `/anchor/*` 支持 token 鉴权、租户前缀校验、限流（可配置）
- 提供 `/metrics` 与 `/alerts/slo` 运维端点（安全模式下 admin 访问）
- OpenClaw 插件支持 startup probe、circuit breaker、快速 bypass 开关

---

## 9) Acceptance Metrics (P0)
### Continuity
1. **Continuity Success Rate**（compaction 后任意问题可连续作答）>= 95%
2. **Context Drift Rate**（答非所问/跑偏）<= 5%
3. **Contradiction Rate**（与已确认事实冲突）<= 2%

### Reliability
4. compaction 前 CCA 写入成功率 >= 99%
5. 有 CCA 前提下“我不记得”类回复率 = 0

### Performance
6. CCA 恢复额外 P95 延迟 <= 1s
7. 超时兜底：20s 内必须返回可用降级回答

---

## 10) Test Plan (必须覆盖)
1. **Compaction Replay**：复现真实事故，验证任意问题连续性
2. **Question Diversity**：状态类/事实类/约束类/追问类混合集
3. **Topic Shift Stress**：多次话题切换后回问旧主题
4. **Contradiction Check**：故意插入旧事实干扰，验证不冲突
5. **Latency Under Load**：并发下恢复延迟

当前可执行测试资产：
- `scripts/run_openclaw_remote_behavioral_ab.py`（真实 `/compact`）
- `scripts/run_openclaw_remote_behavioral_reset_ab.py`（真实 `/reset`）
- `scripts/run_openclaw_remote_behavioral_matrix.py`（compact + reset 矩阵）
- `scripts/run_openclaw_remote_stability_loop.py`（稳定性轮跑）
- `scripts/run_openclaw_remote_nightly_gate.py`（质量门禁）
- `mvp/data/ab_cases_quality.jsonl`（扩展质量数据集）

评估模式：
- strict：严格 token 命中
- semantic：语义变体命中（含数值/单位别名与中英文 token）

---

## 11) Milestones
### Week 1
- CCA schema + 生成器 + local 持久化
- 基础 compaction hook

### Week 2
- 任意问题连续性回答链路打通
- 回放测试集（含真实事故样本）

### Week 3
- hybrid 模式（TiDB）
- 指标采集与看板

### Week 4
- 灰度验证 + Go/No-Go

---

## 12) Go/No-Go Rule
满足以下条件才进入 P1：
1. Continuity Success Rate >= 95%
2. Contradiction Rate <= 2%
3. P95 额外延迟 <= 1s
4. 真实会话回放 >= 3 组通过

当前工程门禁补充（nightly）：
- compact strict delta >= 0.20
- reset strict delta >= 0.20
- compact semantic delta >= 0.30
- reset semantic delta >= 0.30
- stability pass rate = 1.0

不满足则不扩 scope，先修连续性质量。

---

## 13) Multi-Role Self-Review (Condensed)
### CEO View
- 价值是否可感知：是（“不失忆”用户直接感知）
- 是否可讲故事：是（compaction 前后对比 demo）
- 决策：Go（限 P0 范围）

### CTO View
- 实现复杂度：中等（hook + schema + injection）
- 风险：抽取质量与延迟
- 对策：版本化锚点 + 严格指标门控

### CPO View
- 用户核心收益明确：连续对话可信度提升
- 范围控制：必须禁止 P0 膨胀到“大而全 memory”

### GTM View
- 对外一句话：
  - **“Context compressed, continuity preserved.”**
- 首发资产：真实事故复现 + 修复前后对比

---

## 14) FAQ (Merged)
### Q1: 这是检索问题吗？
不是核心。核心是 compaction 后连续性上下文丢失。

### Q2: 为什么不是只做“进展问答”？
因为用户会问任意后续问题，目标是全问题类型连续性。

### Q3: TiDB 必须吗？
P0 不强制；生产推荐 hybrid 提升跨实例恢复能力。

### Q4: 如何证明有效？
看 Continuity/Contradiction/Latency 三组指标，不看主观感受。

### Q5: P0 后扩什么？
类型化记忆治理、冲突消解、生命周期管理。
