# MVP Demo — Compaction-Safe Continuity (Standalone)

This folder contains **demo-only MVP code** isolated from production design/code.

## What this MVP verifies
After context compaction, answers remain continuous for mixed question types by using a lightweight continuity anchor.

## Run
```bash
cd mvp
python3 src/run_mvp.py
```

## Output
- Console summary
- `reports/mvp_results.json`

## Notes
- Local-only, file-based anchor
- No OpenClaw core modification
- Demo validation only
