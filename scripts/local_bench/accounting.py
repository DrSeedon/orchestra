"""Incremental receipts; absent closing usage is never reported as zero spend."""
import math


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError('usage/cost must be finite and non-negative')
    return value


class Accounting:
    def __init__(self, runtime, prices=None):
        self.runtime = runtime
        self.prices = prices or {}
        self.final = False
        self.reported_cost = None
        self.usage = {}
        self.messages = {}
        self.errors = []
        self.active_message = None
        self.completed_messages = set()

    def feed(self, row):
        try:
            kind = row.get('type')
            if self.final:
                return False
            if kind in ('bench.usage', 'bench.result'):
                if self.runtime != 'fixture':
                    return False
                self.usage = {k: number(v) for k, v in row.get('usage', {}).items()}
                if row.get('cost_usd') is not None:
                    self.reported_cost = number(row['cost_usd'])
                self.final = kind == 'bench.result'
                if self.final and row.get('cost_usd') is None:
                    self.reported_cost = None
                return True
            if self.runtime == 'codex' and kind == 'turn.completed':
                self.usage = {k: number(v) for k, v in row.get('usage', {}).items()}
                self.final = True
                return True
            if self.runtime == 'claude' and kind == 'result':
                self.usage = {k: number(v) for k, v in row.get('usage', {}).items() if isinstance(v, (int, float))}
                if row.get('total_cost_usd') is not None:
                    self.reported_cost = number(row['total_cost_usd'])
                self.final = True
                return True
            if self.runtime == 'claude' and kind == 'stream_event':
                event = row.get('event', {})
                if event.get('type') == 'message_start':
                    msg = event.get('message', {})
                    self.active_message = msg.get('id')
                    self.merge_message(self.active_message, msg.get('usage', {}))
                    return True
                if event.get('type') == 'message_delta' and self.active_message:
                    self.merge_message(self.active_message, event.get('usage', {}))
                    return True
                if event.get('type') == 'message_stop' and self.active_message:
                    self.completed_messages.add(self.active_message)
                    self.active_message = None
                    return True
            if self.runtime == 'claude' and kind == 'assistant':
                msg = row.get('message', {})
                if msg.get('id'):
                    self.merge_message(msg['id'], msg.get('usage', {}))
                    return True
        except (ValueError, TypeError, AttributeError) as error:
            self.errors.append(str(error))
        return False

    def merge_message(self, identity, usage):
        if not identity:
            return
        previous = self.messages.setdefault(identity, {})
        for key, value in usage.items():
            if isinstance(value, (int, float)):
                previous[key] = max(previous.get(key, 0), number(value))
        self.usage = {key: sum(m.get(key, 0) for m in self.messages.values()) for key in ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')}

    def receipt(self):
        cost = self.reported_cost
        cost_source = 'provider_final' if self.final else 'progress'
        if cost is None and self.prices and self.usage:
            u = self.usage
            fresh = u.get('input_tokens', 0)
            cached = u.get('cached_input_tokens', 0) if self.runtime == 'codex' else u.get('cache_read_input_tokens', 0)
            created = u.get('cache_write_input_tokens', 0) if self.runtime == 'codex' else u.get('cache_creation_input_tokens', 0)
            if self.runtime == 'codex':
                cached = min(cached, fresh)
                created = min(created, max(0, fresh - cached))
                fresh = max(0, fresh - cached - created)
            cost = (fresh * self.prices['input'] + cached * self.prices['cached_input'] + created * self.prices['cache_write'] + u.get('output_tokens', 0) * self.prices['output']) / 1_000_000
            cost_source = 'configured_rates'
        complete = self.final and cost is not None and not self.errors
        return {'status': 'invalid' if self.errors else 'complete' if complete else ('unpriced' if self.final else ('partial' if self.usage or cost is not None else 'missing')),
                'final_received': self.final, 'cost_usd': cost if complete else None,
                'observed_cost_usd': cost, 'cost_source': cost_source if cost is not None else None,
                'usage': self.usage.copy(), 'inflight_message': self.active_message, 'completed_messages': len(self.completed_messages), 'errors': self.errors.copy(), 'synthetic': self.runtime == 'fixture'}
