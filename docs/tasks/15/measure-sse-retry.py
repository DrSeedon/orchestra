"""#15 — чем быстрее ловится возвращение сервера: родным ретраем EventSource
или нынешней схемой close + setTimeout + опрос.

Свой одноразовый SSE-сервер на свободном порту (сервис orchestra не трогаем):
поднять → уронить → через паузу поднять снова → замерить, через сколько каждая
из двух схем получила первое событие после возврата.
"""
import asyncio, json, socket, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from playwright.async_api import async_playwright

PORT = 8791


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/sse"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                while True:
                    self.wfile.write(f"data: {json.dumps({'t': time.time()})}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(0.5)
            except Exception:
                return
        else:
            body = b"<!doctype html><meta charset=utf-8><body>ok</body>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


def serve():
    """Отдельный ПРОЦЕСС: только его убийство рвёт живые SSE-сокеты.
    srv.shutdown() внутри процесса перестаёт принимать новые, а открытый поток живёт —
    на этом первый заход и провалился (onerror 0 раз, поток не рвался)."""
    import subprocess
    p = subprocess.Popen(["python3", "/tmp/m15_sse_srv.py", str(PORT)])
    time.sleep(0.8)
    return p


async def main():
    srv = serve()
    async with async_playwright() as p:
        br = await p.chromium.launch(args=["--no-sandbox"])
        page = await br.new_page()
        await page.goto(f"http://127.0.0.1:{PORT}/")
        await page.evaluate(f"""() => {{
          window.R = {{native: null, manual: null, nativeErr: 0, manualErr: 0, down: null}};
          // A. родной ретрай: onerror НЕ закрываем, браузер переподключается сам
          const a = new EventSource('http://127.0.0.1:{PORT}/sse');
          a.onmessage = () => {{ if (R.down && R.native === null) R.native = performance.now() - R.down; }};
          a.onerror = () => {{ R.nativeErr++; }};
          // B. нынешняя схема: close + setTimeout(2000) + повторное открытие
          const openB = () => {{
            const b = new EventSource('http://127.0.0.1:{PORT}/sse');
            b.onmessage = () => {{ if (R.down && R.manual === null) R.manual = performance.now() - R.down; }};
            b.onerror = () => {{ R.manualErr++; b.close(); setTimeout(openB, 2000); }};
          }};
          openB();
        }}""")
        await page.wait_for_timeout(2000)

        srv.kill(); srv.wait()
        await page.evaluate("() => { R.down = performance.now(); R.native = null; R.manual = null; }")
        print("сервер погашен, держим паузу 6 с (как реальный старт orchestra)")
        await page.wait_for_timeout(6000)

        # порт мог остаться в TIME_WAIT — поднимаем с SO_REUSEADDR (он в ThreadingHTTPServer по умолчанию)
        srv = serve()
        t_up = time.time()
        await page.wait_for_timeout(8000)
        r = await page.evaluate("() => R")
        print(f"\nпосле возврата сервера (пауза 6 с):")
        print(f"  родной ретрай EventSource : "
              f"{'нет события' if r['native'] is None else str(round(r['native'] - 6000)) + ' мс'} "
              f"(onerror сработал {r['nativeErr']} раз)")
        print(f"  close + setTimeout(2000)  : "
              f"{'нет события' if r['manual'] is None else str(round(r['manual'] - 6000)) + ' мс'} "
              f"(onerror сработал {r['manualErr']} раз)")
        srv.kill()
        await br.close()


asyncio.run(main())
