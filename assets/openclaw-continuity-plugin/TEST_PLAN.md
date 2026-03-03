# Continuity Quality Plan (Compact + Reset)

This test plan extends the current benchmark set to cover quality, performance, and stability risks.

## Existing Coverage (already in repo)

- `scripts/run_openclaw_remote_behavioral_ab.py` (real `/compact`, next-day session switch)
- `scripts/run_openclaw_remote_behavioral_reset_ab.py` (real `/reset`, next-day session switch)
- `scripts/run_openclaw_remote_behavioral_matrix.py` (compact + reset matrix)

## New Coverage Added

- `mvp/data/ab_cases_quality.jsonl`
  - `releaseops_01`: staged rollout policy + rollback threshold consistency
  - `security_01`: security constraint precision + emergency revocation facts
  - `global_01`: bilingual (ZH/EN) compliance constraints
- `scripts/run_openclaw_remote_stability_loop.py`
  - Repeats compact/reset rounds and reports pass-rate + runtime variability
- `scripts/run_openclaw_remote_nightly_gate.py`
  - Runs quality compact + quality reset + stability loop (`--stability-rounds 5` by default)
  - Enforces explicit pass/fail thresholds for strict/semantic delta and stability metrics

## Quality Gates

For each benchmark run:

1. **Correctness**
   - `delta_strict > 0` for both compact and reset
   - `delta_semantic >= delta_strict`

2. **Performance**
   - Track `elapsed_sec` per run
   - Keep stability-loop `elapsed_p95_sec` within operational budget for selected case count

3. **Stability**
   - No script exceptions/timeouts
   - Stability loop round pass-rate = 100% for smoke profile (`--max-cases 1 --rounds 2`)

## Recommended Execution Order

1. Local regression: `PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests`
2. Existing matrix: `scripts/run_openclaw_remote_behavioral_matrix.py`
3. New quality cases (compact + reset):
   - `run_openclaw_remote_behavioral_ab.py --data mvp/data/ab_cases_quality.jsonl`
   - `run_openclaw_remote_behavioral_reset_ab.py --data mvp/data/ab_cases_quality.jsonl`
4. Stability loop smoke:
   - `run_openclaw_remote_stability_loop.py --data mvp/data/ab_cases_quality.jsonl --max-cases 1 --rounds 2`
5. Nightly gate (recommended CI entry):
   - `run_openclaw_remote_nightly_gate.py --data mvp/data/ab_cases_quality.jsonl --stability-rounds 5`
