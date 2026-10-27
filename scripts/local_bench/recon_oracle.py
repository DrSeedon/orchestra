"""Deterministic scorer for code-reconnaissance answers (no model judge).

Run as the benchmark oracle: `recon_oracle.py GOLDEN RESPONSE [TRANSCRIPT]` from the root
of the frozen source snapshot. The answer is JSON `{"answer": {...}, "evidence": [{"path",
"start", "end"}]}`. Exit 0 only when every golden check is exact, every cited span is real
and every required anchor line is covered. Metrics always go to stdout as one JSON object.
"""
import json
import re
import sys
from pathlib import Path


def parse_answer(text):
    """Whole text, else last fenced block, else last balanced object that has an `answer` key."""
    text = text.strip()
    candidates = [text]
    candidates += re.findall(r'```(?:json)?\s*(.*?)```', text, flags=re.S)[::-1]
    for start in [m.start() for m in re.finditer(r'\{', text)]:
        depth = 0
        for end in range(start, len(text)):
            depth += (text[end] == '{') - (text[end] == '}')
            if depth == 0:
                candidates.append(text[start:end + 1])
                break
    for raw in candidates:
        try:
            value = json.loads(raw)
        except ValueError:
            continue
        if isinstance(value, dict) and isinstance(value.get('answer'), dict):
            return value
    return None


def norm(item, keys=None):
    if keys and isinstance(item, dict):
        return tuple(norm(item.get(k, '')) for k in keys)
    if isinstance(item, bool) or item is None:
        return item
    text = re.sub(r'\s+', ' ', str(item).replace('`', '')).strip().casefold()
    return text[2:] if text.startswith('./') else text


def lookup(root, dotted):
    for part in dotted.split('.'):
        if not isinstance(root, dict) or part not in root:
            return None
        root = root[part]
    return root


def lcs(a, b):
    table = [[0] * (len(b) + 1) for _ in a] + [[0] * (len(b) + 1)]
    for i in range(len(a) - 1, -1, -1):
        for j in range(len(b) - 1, -1, -1):
            table[i][j] = table[i + 1][j + 1] + 1 if a[i] == b[j] else max(table[i + 1][j], table[i][j + 1])
    return table[0][0]


def check_score(check, answer):
    actual = lookup(answer, check['path'])
    keys = check.get('item_keys')
    expected = check['expected']
    if check['kind'] == 'equals':
        return 1.0 if norm(actual) == norm(expected) else 0.0
    if not isinstance(actual, list):
        return 0.0
    got = [norm(x, keys) for x in actual]
    want = [norm(x, keys) for x in expected]
    if check['kind'] == 'set':
        common = len(set(got) & set(want))
        if not got or not want:
            return 1.0 if got == want else 0.0
        precision, recall = common / len(set(got)), common / len(set(want))
        score = 0.0 if not common else 2 * precision * recall / (precision + recall)
        return score if len(got) == len(set(got)) else min(score, 0.99)
    common = lcs(got, want)
    return 1.0 if got == want else 2 * common / (len(got) + len(want)) if got and want else 0.0


def evidence_metrics(golden, evidence, root):
    cited, invalid = [], 0
    max_span = golden.get('max_span', 120)
    for item in evidence if isinstance(evidence, list) else []:
        try:
            path, start, end = str(item['path']), int(item['start']), int(item['end'])
        except (KeyError, TypeError, ValueError):
            invalid += 1
            continue
        file = (root / path).resolve()
        if '..' in Path(path).parts or not file.is_relative_to(root) or not file.is_file():
            invalid += 1
            continue
        lines = file.read_text(errors='replace').splitlines()
        if not (1 <= start <= end <= len(lines)) or end - start + 1 > max_span:
            invalid += 1
            continue
        cited.append((path, start, end, lines))
    covered = []
    for anchor in golden.get('anchors', []):
        pattern = re.compile(anchor['pattern'])
        covered.append(any(
            path == anchor['path'] and any(pattern.search(line) for line in lines[start - 1:end])
            for path, start, end, lines in cited))
    total = len(evidence) if isinstance(evidence, list) else 0
    return {'citations': total, 'invalid_citations': invalid, 'anchors': len(covered), 'anchors_covered': sum(covered)}


def transcript_metrics(path):
    commands = 0
    try:
        lines = Path(path).read_text(errors='replace').splitlines()
    except OSError:
        return {'tool_calls': None}
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        item = row.get('item') if isinstance(row, dict) else None
        if isinstance(item, dict) and item.get('type') in {'command_execution', 'mcp_tool_call', 'file_change'} and row.get('type') == 'item.completed':
            commands += 1
    return {'tool_calls': commands}


def score(golden, response_text, root, transcript=None):
    parsed = parse_answer(response_text)
    metrics = {'task_id': golden['task_id'], 'parsed': parsed is not None}
    if transcript:
        metrics.update(transcript_metrics(transcript))
    if parsed is None:
        metrics.update({'checks': len(golden['checks']), 'checks_exact': 0, 'check_score': 0.0, 'pass': False,
                        'false_completion': bool(response_text.strip())})
        return metrics
    scores = {c['id']: check_score(c, parsed) for c in golden['checks']}
    evidence = evidence_metrics(golden, parsed.get('evidence'), root)
    metrics.update(evidence)
    metrics.update({'checks': len(scores), 'checks_exact': sum(v == 1.0 for v in scores.values()),
                    'check_scores': scores, 'check_score': sum(scores.values()) / len(scores),
                    'false_completion': False})
    metrics['pass'] = (metrics['checks_exact'] == metrics['checks'] and evidence['invalid_citations'] == 0
                       and evidence['anchors_covered'] == evidence['anchors'])
    return metrics


def main(argv):
    golden = json.loads(Path(argv[1]).read_text())
    response = Path(argv[2]).read_text(errors='replace') if Path(argv[2]).is_file() else ''
    result = score(golden, response, Path.cwd().resolve(), argv[3] if len(argv) > 3 else None)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
