#!/usr/bin/env python3
import json
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "ab_cases.jsonl"
OUT = ROOT / "reports" / "openclaw_compact_ab_results.json"


def run_cmd(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(cmd)}\n{p.stderr}\n{p.stdout}")
    return p.stdout


def agent(session_id: str, message: str):
    out = run_cmd([
        "openclaw",
        "agent",
        "--session-id",
        session_id,
        "--message",
        message,
        "--json",
    ])
    data = json.loads(out)
    payloads = data.get("result", {}).get("payloads", [])
    txt = "\n".join(p.get("text", "") for p in payloads if p.get("text"))
    return txt.strip(), data


def load_cases():
    return [json.loads(l) for l in DATA.read_text(encoding="utf-8").splitlines() if l.strip()]


def build_anchor(turns):
    keep = []
    keys = [
        "Regulatory path", "Primary endpoint", "Decision:", "Critical rule", "Hard timeout",
        "Rollback trigger", "threshold", "Retention", "Constraint", "policy"
    ]
    for t in turns:
        if any(k.lower() in t.lower() for k in keys):
            keep.append(t)
    return keep


def hit(ans: str, expected):
    a = ans.lower()
    return all(e.lower() in a for e in expected)


def run_case(case):
    control_sid = f"ab-control-{case['case_id']}-{uuid.uuid4().hex[:8]}"
    exp_sid = f"ab-exp-{case['case_id']}-{uuid.uuid4().hex[:8]}"

    # Prime both sessions with same turns
    for t in case["turns"]:
        agent(control_sid, t)
        agent(exp_sid, t)

    # Trigger real OpenClaw compaction in both sessions
    compact_control_reply, _ = agent(control_sid, "/compact")
    compact_exp_reply, _ = agent(exp_sid, "/compact")

    anchor_lines = build_anchor(case["turns"])
    anchor_block = "\n".join(f"- {x}" for x in anchor_lines)

    rows = []
    for q in case["queries"]:
        control_ans, _ = agent(control_sid, q["q"])

        exp_prompt = (
            "Use the continuity anchor below to preserve context after compaction.\n"
            "Continuity Anchor:\n"
            f"{anchor_block}\n\n"
            f"Question: {q['q']}\n"
            "Answer in one short sentence."
        )
        exp_ans, _ = agent(exp_sid, exp_prompt)

        rows.append({
            "case_id": case["case_id"],
            "query": q["q"],
            "expected": q["expected"],
            "control_answer": control_ans,
            "experiment_answer": exp_ans,
            "control_hit": hit(control_ans, q["expected"]),
            "experiment_hit": hit(exp_ans, q["expected"]),
        })

    return {
        "case_id": case["case_id"],
        "domain": case["domain"],
        "control_session_id": control_sid,
        "experiment_session_id": exp_sid,
        "compact_control_reply": compact_control_reply,
        "compact_experiment_reply": compact_exp_reply,
        "rows": rows,
    }


def main():
    t0 = time.time()
    cases = load_cases()
    reports = []
    c_hits = 0
    e_hits = 0
    total = 0

    for c in cases:
        rep = run_case(c)
        reports.append(rep)
        for r in rep["rows"]:
            total += 1
            c_hits += int(r["control_hit"])
            e_hits += int(r["experiment_hit"])

    result = {
        "mode": "openclaw-real-compact",
        "total_queries": total,
        "control_recall": c_hits / total,
        "experiment_recall": e_hits / total,
        "delta": (e_hits - c_hits) / total,
        "elapsed_sec": round(time.time() - t0, 2),
        "cases": reports,
        "disclosure": "Compaction is real via OpenClaw /compact. Experiment arm adds external continuity-anchor block in prompt (MVP behavior).",
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== OpenClaw Real Compact A/B ===")
    print(f"Queries: {total}")
    print(f"Control recall:    {result['control_recall']:.2%}")
    print(f"Experiment recall: {result['experiment_recall']:.2%}")
    print(f"Delta:             {result['delta']:.2%}")
    print(f"Elapsed:           {result['elapsed_sec']} sec")
    print(f"Report:            {OUT}")


if __name__ == "__main__":
    main()
