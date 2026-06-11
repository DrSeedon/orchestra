"""P2 guard: the HTTP route surface must not change during the main.py → routes/ drain."""

EXPECTED = None  # filled below on first import of the app


def test_route_surface_snapshot():
    from app.main import app
    surface = sorted(
        (r.path, tuple(sorted(r.methods)))
        for r in app.routes if hasattr(r, "methods") and r.methods
    )
    # snapshot taken at P1 (pre-drain); P2 must keep it byte-identical
    import json
    from pathlib import Path
    snap_file = Path(__file__).parent / "route_surface_snapshot.json"
    if not snap_file.exists():
        snap_file.write_text(json.dumps(surface, indent=1, ensure_ascii=False))
    expected = [tuple([p, tuple(m)]) for p, m in json.loads(snap_file.read_text())]
    assert surface == expected, (
        "route surface changed — paths/methods must stay identical during refactor")
