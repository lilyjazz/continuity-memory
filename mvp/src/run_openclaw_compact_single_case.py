#!/usr/bin/env python3
import json
import subprocess
import uuid
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "ab_cases.jsonl"
OUT = ROOT / "reports" / "openclaw_compact_single_case_medtech.json"


def run_cmd(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"cmd failed: {' '.join(cmd)}\nSTDERR:\n{p.stderr}\nSTDOUT:\n{p.stdout}")
    return p.stdout


def agent(session_id: str, message: str):
    out = run_cmd([
        "openclaw", "agent", "--session-id", session_id, "--message", message, "--json"
    ])
    data = json.loads(out)
    payloads = data.get("result", {}).get("payloads", [])
    txt = "\n".join(p.get("text", "") for p in payloads if p.get("text")).strip()
    return txt, data


def load_medtech_case():
    for line in DATA.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        c = json.loads(line)
        if c.get("case_id") == "medtech_01":
            return c
    raise RuntimeError("medtech_01 not found")


def build_anchor(turns):
    keep = []
    for t in turns:
        low = t.lower()
        if any(k in low for k in [
            "regulatory path", "primary endpoint", "decision:", "constraint", "policy", "timeline"
        ]):
            keep.append(t)
    return keep


def hit(ans, expected):
    a = ans.lower()
    return all(e.lower() in a for e in expected)


def main():
    case = load_medtech_case()
    control_sid = f"ab-control-{case['case_id']}-{uuid.uuid4().hex[:8]}"
    exp_sid = f"ab-exp-{case['case_id']}-{uuid.uuid4().hex[:8]}"

    transcript_log = {"control": [], "experiment": []}

    isolation_instruction = (
        "Benchmark rule: Use ONLY facts from this session conversation turns. "
        "Ignore MEMORY.md, workspace files, prior chats, and external memory. "
        "Do not cite file sources."
    )
    agent(control_sid, isolation_instruction)
    agent(exp_sid, isolation_instruction)

    for turn in case["turns"]:
        c_ans, _ = agent(control_sid, turn)
        e_ans, _ = agent(exp_sid, turn)
        transcript_log["control"].append({"input": turn, "assistant": c_ans})
        transcript_log["experiment"].append({"input": turn, "assistant": e_ans})

    c_compact_reply, _ = agent(control_sid, "/compact")
    e_compact_reply, _ = agent(exp_sid, "/compact")

    anchor_lines = build_anchor(case["turns"])
    anchor_block = "\n".join(f"- {x}" for x in anchor_lines)

    rows = []
    for q in case["queries"]:
        control_ans, _ = agent(control_sid, q["q"])
        exp_prompt = (
            "Use the continuity anchor below to preserve context after compaction.\n"
            f"Continuity Anchor:\n{anchor_block}\n\n"
            f"Question: {q['q']}\n"
            "Answer in one short sentence."
        )
        exp_ans, _ = agent(exp_sid, exp_prompt)
        rows.append({
            "query": q["q"],
            "expected": q["expected"],
            "control_answer": control_ans,
            "experiment_answer": exp_ans,
            "control_hit": hit(control_ans, q["expected"]),
            "experiment_hit": hit(exp_ans, q["expected"]),
        })

    c_hits = sum(1 for r in rows if r["control_hit"])
    e_hits = sum(1 for r in rows if r["experiment_hit"])

    result = {
        "mode": "openclaw-real-compact-single-case",
        "case_id": case["case_id"],
        "domain": case["domain"],
        "control_session_id": control_sid,
        "experiment_session_id": exp_sid,
        "compact_control_reply": c_compact_reply,
        "compact_experiment_reply": e_compact_reply,
        "rows": rows,
        "control_recall": c_hits / len(rows),
        "experiment_recall": e_hits / len(rows),
        "delta": (e_hits - c_hits) / len(rows),
        "disclosure": "Real OpenClaw /compact used. Experiment adds continuity-anchor prompt block.",
        "generated_at": int(time.time())
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "case_id": case["case_id"],
        "control_recall": result["control_recall"],
        "experiment_recall": result["experiment_recall"],
        "delta": result["delta"],
        "out": str(OUT)
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
