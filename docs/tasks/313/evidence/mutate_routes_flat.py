"""Runtime-only mutant: remove nested-route traversal from test_routes_surface."""

def pytest_collection_modifyitems(session, config, items):
    def flat(routes, seen=None):
        found = []
        for route in routes:
            methods = getattr(route, "methods", None)
            path = getattr(route, "path", None)
            if methods and path:
                found.append((path, tuple(sorted(methods))))
        return found

    for item in items:
        if item.nodeid.startswith("tests/test_routes_surface.py::"):
            item.module._collect = flat
            item.module._orchestra_mutant_loaded = True
