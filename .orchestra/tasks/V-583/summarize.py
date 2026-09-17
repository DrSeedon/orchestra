"""V-583: split each phase into the switch burst and the background polls.

A "burst" request is one the switch itself causes (chat history, per-agent panels,
stream reconnect). Everything else in the phase window is a periodic poller that
would have fired anyway; counting it as switch cost would overstate the switch.
"""

import sys

from analyze import load

BURST = ("/logs?", "/queued-messages", "/context?", "/stream?")
POLL = ("/api/sessions?", "/api/stats?", "/api/models", "/api/files?", "/api/orchestrators")


def kind(url):
    if any(p in url for p in BURST):
        return "burst"
    if any(url.startswith(p) for p in POLL):
        return "poll"
    return "other"


if __name__ == "__main__":
    for path in sys.argv[1:]:
        d, rows = load(path)
        phases = []
        for r in rows:
            if r["phase"] not in phases:
                phases.append(r["phase"])
        print("\n=== %s ===" % path)
        for ph in phases:
            sub = [r for r in rows if r["phase"] == ph]
            burst = [r for r in sub if kind(r["url"]) == "burst"]
            poll = [r for r in sub if kind(r["url"]) != "burst"]
            print(
                "%-34s burst %2d req %7d B | poll %2d req %6d B"
                % (ph, len(burst), sum(r["bytes"] for r in burst),
                   len(poll), sum(r["bytes"] for r in poll))
            )
            for r in burst:
                print("      %-62s %7d B  %6.0f ms" % (r["url"][:62], r["bytes"], r["ms"] or 0))
