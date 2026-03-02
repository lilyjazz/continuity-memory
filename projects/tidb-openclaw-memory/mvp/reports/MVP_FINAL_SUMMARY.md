# MVP Final Summary — OpenClaw Continuity Anchor (Compact + Reset)

Date: 2026-03-01
Scope: Long-form (80-turn) end-to-end tests with real OpenClaw commands.

---

## 1) Objective
Validate whether Continuity Anchor can improve follow-up QA reliability after:
1. `/compact` (context compaction)
2. `/reset` (new sessionId / continuity break)

Test arms per case:
- **Control**: no continuity anchor
- **Experiment**: with continuity anchor
- **Experiment+Fallback (Guarded)**: monotonic guard, never worse than baseline

---

## 2) Key Results

### A. `/compact` Path (real OpenClaw compact)
- `medtech_long_80`: control 0.80 / experiment 0.60 / guarded 0.80
- `finops_long_80`: control 0.60 / experiment 0.60 / guarded 0.60
- `mlops_long_80` (strict+semantic): control 1.00 / experiment 0.80 / guarded 1.00

**Interpretation**
- OpenClaw native compact summary is already strong in many cases.
- Experiment alone may fluctuate by phrasing/scoring strictness.
- Guarded mode successfully enforces “not worse than baseline”.

### B. `/reset` Path (real OpenClaw reset)
Batch summary (`openclaw_reset_three_arm_summary_batch2.json`):
- `medtech_long_80`: control 0.00 / experiment 0.60 / guarded 0.60
- `finops_long_80`: control 0.00 / experiment 0.60 / guarded 0.60
- `mlops_long_80`: control 0.00 / experiment 0.80 / guarded 0.80

**Interpretation**
- After reset, control arm consistently loses continuity (0.00).
- Experiment/Guarded recover substantial context (+60% to +80%).
- This is the strongest MVP evidence for business value.

---

## 3) Performance Snapshot
Observed average latency patterns:
- **Experiment (single-path)**: typically near control, sometimes +5~20%
- **Guarded (dual-path)**: approximately ~2x latency (because two candidates are generated)

Example measured benchmark:
- Baseline avg: 1549 ms
- Enhanced avg: 1825 ms (+17.8%)
- Guarded avg: 4503 ms (+190.7%)

Recommendation:
- Use guarded fallback selectively (high-risk questions), not globally.

---

## 4) Product Conclusions (MVP)
1. **Reset scenario value is proven**:
   continuity anchor materially reduces post-reset answer failure.
2. **Compact scenario needs policy optimization**:
   native compact is already good; anchor should be applied with guardrail.
3. **Guarded fallback is required for production safety**:
   ensures monotonic quality (no degradation vs baseline).

---

## 5) Known Limits
1. Strict scoring can undercount semantically-correct answers.
2. Some fluctuations come from answer phrasing variance.
3. Current fallback implementation in tests is offline guard logic; production should implement in online serving path with risk-gated triggers.

---

## 6) Artifacts (Saved)
Primary reports:
- `mvp/reports/openclaw_compact_single_case_long80.json`
- `mvp/reports/openclaw_reset_single_case_long80.json`
- `mvp/reports/openclaw_compact_three_arm_finops_long80.json`
- `mvp/reports/openclaw_compact_three_arm_mlops_long80.json`
- `mvp/reports/openclaw_reset_three_arm_supplychain_long80.json`
- `mvp/reports/openclaw_reset_three_arm_summary_batch2.json`
- `mvp/reports/guarded_quick_summary.json`

Supporting docs:
- `mvp/reports/MVP_TEST_SUMMARY.md`

---

## 7) Next Step (Post-MVP)
1. Add semantic evaluator as first-class metric beside strict metric.
2. Implement online guarded selection (risk-triggered) in serving path.
3. Expand to 5-case full matrix with compact/reset × strict/semantic × latency confidence intervals.
