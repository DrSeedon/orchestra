import argparse
import asyncio
import json
import sys
from pathlib import Path
from .config import read
from .runner import run
from .isolation import preflight


def main():
    parser = argparse.ArgumentParser(description='Local benchmark runner; no Orchestra integration or automatic provider calls.')
    parser.add_argument('action', choices=['plan', 'run', 'doctor'])
    parser.add_argument('config', nargs='?')
    parser.add_argument('--output', help='new private output directory (never overwritten)')
    parser.add_argument('--allow-provider', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'doctor':
            print(json.dumps(preflight(), ensure_ascii=False, indent=2))
            return 0
        if not args.config:
            parser.error('plan/run require CONFIG.json')
        config = read(args.config)
        if args.action == 'plan':
            print(json.dumps({'name': config['name'], 'mode': 'provider' if config['_provider'] else 'offline_synthetic', 'arms': [a['name'] for a in config['arms']], 'parallel': True, 'budget_usd': config['budget_usd'], 'provider_requires_working_namespaces': config['_provider'], 'config_sha256': config['_config_sha256']}, ensure_ascii=False, indent=2))
            return 0
        if not args.output:
            parser.error('run requires --output')
        result = asyncio.run(run(config, args.output, args.allow_provider))
        print(str(Path(args.output).resolve() / 'report.md'))
        return 0 if result['all_pass'] and result['accounting_complete'] else 1
    except (ValueError, OSError, RuntimeError) as error:
        print(f'local-bench: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
