"""Synthetic actor, never a model: deterministic runner self-test."""
import argparse
import json
from pathlib import Path
import signal
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument('mode', choices=['good', 'bad', 'graceful', 'uncooperative'])
parser.add_argument('--delay', type=float, default=0.15)
args = parser.parse_args()
sys.stdin.read()
Path('calc.py').write_text('def total(values):\n    return sum(values)' + (' + 1' if args.mode == 'bad' else '') + '\n')
# Deliberately emitted bytecode must not count as an unauthorized source change.
Path('__pycache__').mkdir(exist_ok=True)
Path('__pycache__/calc.cpython-312.pyc').write_bytes(b'fixture')
print(json.dumps({'type': 'bench.usage', 'cost_usd': 0.1, 'usage': {'input_tokens': 10}}), flush=True)
def finish(*_):
    print(json.dumps({'type': 'bench.result', 'cost_usd': 0.2, 'usage': {'input_tokens': 10, 'output_tokens': 5}}), flush=True)
    raise SystemExit(0)
if args.mode == 'graceful':
    signal.signal(signal.SIGINT, finish)
    time.sleep(60)
elif args.mode == 'uncooperative':
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(60)
else:
    time.sleep(args.delay)
    finish()
