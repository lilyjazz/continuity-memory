# Reports Directory

`reports/` stores generated benchmark outputs and gate artifacts.

Main report files:

- `openclaw_remote_behavioral_matrix.json`
- `openclaw_remote_behavioral_compact_ab_results.json`
- `openclaw_remote_behavioral_reset_ab_results.json`
- `openclaw_remote_behavioral_quality_compact_ab_results.json`
- `openclaw_remote_behavioral_quality_reset_ab_results.json`
- `openclaw_remote_stability_loop_results.json`
- `openclaw_remote_nightly_gate_results.json`

Round-level artifacts:

- `stability_rounds/compact_round_*.json`
- `stability_rounds/reset_round_*.json`

These files are kept intentionally as reproducible evidence for benchmark and gate results.

## Retention Policy

- Keep only canonical summary reports in Git.
- Treat `stability_rounds/` and ad-hoc JSON dumps as disposable artifacts.
- Store full historical run outputs in CI artifacts or release assets.

Use the pruning utility:

```bash
# Dry run
python3 scripts/prune_reports.py

# Apply deletion
python3 scripts/prune_reports.py --apply
```
