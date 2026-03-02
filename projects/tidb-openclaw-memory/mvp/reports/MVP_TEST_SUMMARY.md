# MVP Test Summary (for customer-facing explanation)

## 1) What this MVP proves
This MVP validates one core claim:

> After context compaction, adding a Continuity Anchor significantly improves follow-up answer recall vs. a control setup.

## 2) Important truth / disclosure
- In this MVP, **compaction is simulated** in code (not an OpenAI official compaction API call).
- We intentionally degraded context to a compacted summary form, then compared:
  - **Control group**: compacted text only
  - **Experiment group**: compacted text + Continuity Anchor facts

This is a transparent demo validation, not yet a full OpenClaw native compact hook integration test.

## 3) Test logic (how it works)
### Dataset
- 3 domain conversations, each with 12 turns:
  1. medical-device-regulatory
  2. payment-risk-ops
  3. llm-platform-ops
- 9 total follow-up queries (3 per case)

### Compaction simulation
- Keep a generic compact summary + last 2 turns
- This simulates information loss from long-thread compression

### Continuity Anchor (experiment only)
- Extract high-value lines via MVP rules:
  - Decision / Critical rule / Hard timeout / Rollback trigger / Regulatory path / Threshold / Policy
  - Key patterns like percentages, durations, IDs
- Build an anchor fact set and append it to compacted context for answering

### Scoring
- Recall hit if all expected keywords for a query appear in answer
- Compare control recall vs experiment recall

## 4) Results
- Total queries: 9
- Control recall: **22.22%**
- Experiment recall: **88.89%**
- Delta: **+66.67%**

Raw report: `mvp/reports/ab_results.json`

## 5) Conversation content (fully visible)
Source file: `mvp/data/ab_cases.jsonl`

Included domains and sample key facts:
- MedTech: FDA 510(k), K123456, sensitivity >= 92%, no cloud PHI export before legal sign-off
- FinOps: chargeback threshold 1.2% weekly, sanctions unresolved => block payouts, no instant payout for tenure < 60 days
- MLOps: hard timeout 20s with graceful degrade, rollback trigger error > 2.5%, debug trace retention 14 days

## 6) Why this is valuable to customers
Customer pain in long conversations is not “more memory volume,” but:
- lost continuity
- contradiction with prior decisions
- inability to answer concrete follow-ups after compaction

This MVP shows a practical fix direction with measurable lift.

## 7) What to say in GTM meetings
- “We ran an A/B under compacted context conditions.”
- “Without continuity anchor, recall dropped sharply; with anchor, recall improved from 22% to 89%.”
- “This is a transparent MVP with simulated compaction; next step is native OpenClaw `/compact` replay validation.”

## 8) Next step (to make it production-grade proof)
1. Replay real OpenClaw sessions
2. Trigger real `/compact` in test flow
3. Re-run A/B with same metrics (recall, contradiction, latency)
4. Publish before/after report with raw prompts + outputs
