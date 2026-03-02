#!/usr/bin/env python3
import json, re, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data' / 'ab_cases.jsonl'
OUT = ROOT / 'reports' / 'ab_results.json'


def load_cases(path):
    return [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]


def compact_text(turns):
    # Simulate realistic compaction loss: keep only generic summary + latest 2 turns
    generic = 'Project discussion summary with goals, constraints, timeline and pending items.'
    tail = ' '.join(turns[-2:])
    return generic + ' ' + tail


def build_anchor(turns):
    # keep high-value facts via simple pattern extraction (MVP rule-based)
    facts = []
    patterns = [r'\b\d+(?:\.\d+)?%\b', r'\b\d+\s*(?:days|hours|seconds|months)\b', r'\b[A-Z]\d{6}\b', r'\b510\(k\)\b']
    for t in turns:
        low = t.lower()
        if any(k in low for k in ['decision:', 'critical rule', 'hard timeout', 'rollback trigger', 'regulatory path', 'threshold', 'policy']):
            facts.append(t)
            continue
        if any(re.search(p, t, re.IGNORECASE) for p in patterns):
            facts.append(t)
    return {'facts': facts, 'summary': ' '.join(turns[:2])}


def answer_from_text(text, q):
    # naive retrieval: return sentence with max token overlap
    sents = re.split(r'(?<=[.!?])\s+', text)
    q_tokens = set(re.findall(r'[a-z0-9%()\.<>-]+', q.lower()))
    best, score = '', -1
    for s in sents:
        st = set(re.findall(r'[a-z0-9%()\.<>-]+', s.lower()))
        ov = len(q_tokens & st)
        if ov > score:
            best, score = s, ov
    return best.strip()


def hit(ans, expected):
    al = ans.lower()
    return all(e.lower() in al for e in expected)


def run():
    cases = load_cases(DATA)
    start = time.time()
    total_q = 0
    c_hits = 0
    e_hits = 0
    rows = []

    for c in cases:
        compacted = compact_text(c['turns'])
        anchor = build_anchor(c['turns'])
        exp_text = compacted + ' ' + ' '.join(anchor['facts'])

        for q in c['queries']:
            total_q += 1
            control_ans = answer_from_text(compacted, q['q'])
            exp_ans = answer_from_text(exp_text, q['q'])
            ch = hit(control_ans, q['expected'])
            eh = hit(exp_ans, q['expected'])
            c_hits += int(ch)
            e_hits += int(eh)
            rows.append({
                'case_id': c['case_id'], 'query': q['q'],
                'control_answer': control_ans, 'experiment_answer': exp_ans,
                'expected': q['expected'], 'control_hit': ch, 'experiment_hit': eh
            })

    res = {
        'total_queries': total_q,
        'control_recall': c_hits / total_q,
        'experiment_recall': e_hits / total_q,
        'delta': (e_hits - c_hits) / total_q,
        'elapsed_ms': int((time.time()-start)*1000),
        'rows': rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
    print('=== Compaction A/B MVP ===')
    print(f"Queries: {total_q}")
    print(f"Control recall:    {res['control_recall']:.2%}")
    print(f"Experiment recall: {res['experiment_recall']:.2%}")
    print(f"Delta:             {res['delta']:.2%}")
    print(f"Elapsed:           {res['elapsed_ms']} ms")
    print(f"Report:            {OUT}")

if __name__ == '__main__':
    run()
