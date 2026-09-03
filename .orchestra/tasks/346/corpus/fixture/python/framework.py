"""Tiny framework shims: only source shape matters to static tools."""


class Router:
    def post(self, path: str):
        def decorate(function):
            return function
        return decorate


class MCP:
    def tool(self):
        def decorate(function):
            return function
        return decorate


router = Router()
mcp = MCP()

