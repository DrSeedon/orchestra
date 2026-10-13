"""Static duration estimates and animation ranges for simple VoiceScene classes."""
from __future__ import annotations

import ast


class UnsupportedTiming(Exception):
    pass


def _number(node: ast.AST, values: dict[str, float | tuple[float, float]]) -> float | tuple[float, float]:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name) and node.id in values:
        return values[node.id]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "left":
        return values.get("__left__", (1.0, 0.0))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = _number(node.operand, values)
        sign = -1 if isinstance(node.op, ast.USub) else 1
        return (value[0] * sign, value[1] * sign) if isinstance(value, tuple) else value * sign
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
        left, right = _number(node.left, values), _number(node.right, values)
        if isinstance(node.op, ast.Add):
            sign = 1
        elif isinstance(node.op, ast.Sub):
            sign = -1
        elif isinstance(node.op, ast.Mult):
            if isinstance(left, tuple) and isinstance(right, tuple):
                raise UnsupportedTiming
            if isinstance(left, tuple):
                return left[0] * right, left[1] * right
            if isinstance(right, tuple):
                return right[0] * left, right[1] * left
            return left * right
        else:
            if isinstance(right, tuple) or right == 0:
                raise UnsupportedTiming
            return (left[0] / right, left[1] / right) if isinstance(left, tuple) else left / right
        if isinstance(left, tuple) or isinstance(right, tuple):
            a = left if isinstance(left, tuple) else (0.0, left)
            b = right if isinstance(right, tuple) else (0.0, right)
            return a[0] + sign * b[0], a[1] + sign * b[1]
        return left + sign * right
    raise UnsupportedTiming


def _literal(node: ast.AST, values: dict[str, float | tuple[float, float]]):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = _literal(node.operand, values)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.Name) and node.id in values:
        return values[node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        return [_literal(item, values) for item in node.elts]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id == "range":
            args = [_literal(arg, values) for arg in node.args]
            return range(*args)
        if node.func.id == "enumerate" and len(node.args) == 1:
            return list(enumerate(_literal(node.args[0], values)))
        if node.func.id == "zip":
            return list(zip(*[_literal(arg, values) for arg in node.args]))
        if node.func.id == "len" and len(node.args) == 1:
            return len(_literal(node.args[0], values))
    raise UnsupportedTiming


def analyze(source: str, class_name: str) -> dict:
    """Return supported static play-time estimates and per-step play ranges."""
    tree = ast.parse(source)
    cls = next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name), None)
    construct = next((node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and node.name == "construct"), None) if cls else None
    if construct is None:
        return {"complete": False, "steps": []}
    result, animation = [], 0

    def visit(statements, values):
        nonlocal animation
        total = (0.0, 0.0)
        for node in statements:
            if isinstance(node, (ast.With, ast.AsyncWith)):
                step = None
                for item in node.items:
                    call = item.context_expr
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "step":
                        try:
                            step = int(_literal(call.args[0], values))
                        except (UnsupportedTiming, ValueError, TypeError):
                            raise UnsupportedTiming
                if step is None:
                    nested, _ = visit(node.body, values)
                    total = _add(total, nested)
                    continue
                start = animation
                try:
                    step_values = dict(values)
                    step_values["__left__"] = (1.0, 0.0)
                    duration, _ = visit(node.body, step_values)
                    result.append({"step": step, "first_animation": start, "last_animation": animation,
                                   "play_slope": duration[0], "play_fixed_s": duration[1]})
                    total = _add(total, duration)
                except UnsupportedTiming:
                    raise
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.value.id == "self":
                    if call.func.attr in ("play", "wait"):
                        if "__left__" not in values:
                            raise UnsupportedTiming
                        duration = 1.0
                        if call.func.attr == "wait" and call.args:
                            duration = _number(call.args[0], values)
                        for kw in call.keywords:
                            if kw.arg == "run_time":
                                duration = _number(kw.value, values)
                        total = _add(total, duration)
                        values["__left__"] = _subtract(values.get("__left__", (1.0, 0.0)), duration)
                        animation += 1
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value = node.value
                try:
                    evaluated = _number(value, values)
                except UnsupportedTiming:
                    try:
                        evaluated = _literal(value, values)
                    except UnsupportedTiming:
                        continue
                for target in targets:
                    if isinstance(target, ast.Name):
                        values[target.id] = evaluated
            elif isinstance(node, ast.For):
                if not any(isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute)
                           and isinstance(item.func.value, ast.Name) and item.func.value.id == "self"
                           and item.func.attr in ("play", "wait") for item in ast.walk(node)):
                    continue
                try:
                    iterable = _literal(node.iter, values)
                except UnsupportedTiming:
                    raise
                iteration_total = (0.0, 0.0)
                for value in iterable:
                    nested_values = dict(values)
                    if isinstance(node.target, ast.Name):
                        nested_values[node.target.id] = value
                    elif isinstance(node.target, (ast.Tuple, ast.List)) and isinstance(value, (tuple, list)):
                        for target, item in zip(node.target.elts, value, strict=True):
                            if not isinstance(target, ast.Name):
                                raise UnsupportedTiming
                            nested_values[target.id] = item
                    else:
                        raise UnsupportedTiming
                    nested, _ = visit(node.body, nested_values)
                    iteration_total = _add(iteration_total, nested)
                    if "__left__" in nested_values:
                        values["__left__"] = nested_values["__left__"]
                total = _add(total, iteration_total)
                if node.orelse:
                    raise UnsupportedTiming
            elif isinstance(node, ast.If):
                if any(isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute)
                       and isinstance(item.func.value, ast.Name) and item.func.value.id == "self"
                       and item.func.attr in ("play", "wait") for item in ast.walk(node)):
                    raise UnsupportedTiming
        return total, values

    try:
        total, _ = visit(construct.body, {})
        result.sort(key=lambda row: row["step"])
        return {"complete": True, "steps": result, "play_slope": total[0], "play_fixed_s": total[1]}
    except UnsupportedTiming:
        return {"complete": False, "steps": []}


def _add(left, right):
    a = left if isinstance(left, tuple) else (0.0, left)
    b = right if isinstance(right, tuple) else (0.0, right)
    return a[0] + b[0], a[1] + b[1]


def _subtract(left, right):
    a = left if isinstance(left, tuple) else (0.0, left)
    b = right if isinstance(right, tuple) else (0.0, right)
    return a[0] - b[0], a[1] - b[1]


def check(analysis: dict, durations: list[float]) -> dict:
    if not analysis["complete"]:
        return {"complete": False, "overruns": []}
    if [row["step"] for row in analysis["steps"]] != list(range(len(durations))):
        return {"complete": False, "overruns": []}
    rows = []
    for row in analysis["steps"]:
        if row["step"] >= len(durations):
            return {"complete": False, "overruns": []}
        remaining = durations[row["step"]] - (row["play_slope"] * durations[row["step"]] + row["play_fixed_s"])
        rows.append({**row, "budget_s": durations[row["step"]], "remaining_s": round(remaining, 4)})
    return {"complete": True, "steps": rows,
            "overruns": [row["step"] for row in rows if row["remaining_s"] < -0.05]}


def selected_range(analysis: dict, first_step: int, last_step: int) -> tuple[int, int]:
    rows = [row for row in analysis["steps"] if first_step <= row["step"] <= last_step]
    if not rows or any(not row["first_animation"] < row["last_animation"] for row in rows):
        raise ValueError("preview step has no statically indexed self.play/self.wait calls")
    # Manim numbers the initial VoiceScene pre-roll wait as play 0; a completed
    # VoiceScene step adds one tail wait before the next step's explicit calls.
    first = 1 + rows[0]["first_animation"] + rows[0]["step"]
    last = 1 + rows[-1]["last_animation"] - 1 + rows[-1]["step"]
    return first, last
