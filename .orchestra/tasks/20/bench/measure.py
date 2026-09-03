"""Замер стоимости вызова: время и peak RSS ТОЛЬКО своего дерева процессов.

На хосте уже крутится чужой chromium (другой воркер) — суммировать все процессы по имени
нельзя, замер будет чужим. Считаем только потомков запущенного нами интерпретатора.
"""
import os
import subprocess
import sys
import threading
import time


def tree_rss_mb(root_pid):
    """Сумма RSS процесса и всех его потомков, МБ."""
    try:
        out = subprocess.run(["ps", "-eo", "pid,ppid,rss", "--no-headers"],
                             capture_output=True, text=True, timeout=5).stdout
    except subprocess.TimeoutExpired:
        return 0.0
    kids, rss = {}, {}
    for line in out.splitlines():
        pid, ppid, r = line.split()
        kids.setdefault(int(ppid), []).append(int(pid))
        rss[int(pid)] = int(r)
    total, stack = 0, [root_pid]
    while stack:
        p = stack.pop()
        total += rss.get(p, 0)
        stack.extend(kids.get(p, []))
    return total / 1024


def run(cmd, cwd):
    peak = [0.0]
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def sample():
        while proc.poll() is None:
            peak[0] = max(peak[0], tree_rss_mb(proc.pid))
            time.sleep(0.05)

    th = threading.Thread(target=sample, daemon=True)
    th.start()
    out = proc.communicate()[0]
    th.join(timeout=1)
    return time.perf_counter() - t0, peak[0], out


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    variants = {
        "matplotlib": ["/home/kesha/scratch-20/mplenv/bin/python", "render_mpl.py", "out"],
        "pillow": ["/home/kesha/orchestra/.venv/bin/python", "render_pil.py", "out"],
        "html+chromium": ["/home/kesha/orchestra/.venv/bin/python", "render_html.py", "out"],
    }
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    for name, cmd in variants.items():
        print(f"\n### {name}")
        for i in range(reps):
            wall, peak, out = run(cmd, here)
            per = [l for l in out.splitlines() if ":" in l and "ms" in l]
            print(f"  прогон {i+1}: wall {wall:.2f} с, peak RSS дерева {peak:.0f} МБ")
            for l in per:
                print(f"      {l}")
