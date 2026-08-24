from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def main() -> None:
    for rel in ("app/routes/proxy.py", "app/proxy_manager.py", "app/ssh_tunnel.py"):
        assert not (ROOT / rel).exists(), f"legacy proxy/tunnel file remains: {rel}"
    main_src = (ROOT / "app/main.py").read_text(encoding="utf-8")
    for marker in ("from app.routes.proxy", "start_tunnel", "stop_tunnel"):
        assert marker not in main_src, f"legacy proxy/tunnel owner remains: {marker}"
    env_src = (ROOT / "app/runtime_env.py").read_text(encoding="utf-8")
    for key in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "INTERNAL_TOKEN"):
        assert key in env_src, f"live MCP client env key lost: {key}"


if __name__ == "__main__":
    main()
