"""Read-only evidence collection; no provider requests or private runtime data."""
from pathlib import Path
import hashlib
import json
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[3]
TASK = Path(__file__).resolve().parent

def capture(name, command):
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=60)
    text = '$ ' + ' '.join(command) + '\n' + result.stdout
    if result.stderr:
        text += '\n[stderr]\n' + result.stderr
    text += f'\n[exit {result.returncode}]\n'
    (TASK / 'logs' / name).write_text(text)
    print(name, 'exit', result.returncode, 'chars', len(text))

def fetch(name, url):
    try:
        with urllib.request.urlopen(url, timeout=40) as response:
            data = response.read()
        (TASK / 'sources' / name).write_bytes(data)
        row = {'file': name, 'url': url, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    except Exception as exc:
        row = {'file': name, 'url': url, 'error': str(exc)}
    print(json.dumps(row, ensure_ascii=False))
    return row

if __name__ == '__main__':
    capture('image-code-search.txt', ['rg', '-n', 'image|photo|attachment|resize|thumbnail|view_image|vision|localImage',
        'app/backend_claude.py', 'app/backend_codex.py', 'app/backend_hub.py', 'app/harness',
        'app/tg_bridge.py', 'app/routes', 'app/static/js/chat.js', 'app/initial_deliveries.py',
        'app/backend_harness.py', 'app/backend_grok.py', 'app/hub_workspace.py', 'app/models.py'])
    capture('tool-availability.txt', ['bash', '-c', 'command -v tesseract; command -v node; command -v fc-match'])
    capture('tesseract-version.txt', ['bash', '-c', 'tesseract --version'])
    files = ['app/models.py', 'app/harness/images.py', 'app/harness/llm.py', 'app/harness/tools.py',
        'app/backend_claude.py', 'app/backend_codex.py', 'app/backend_hub.py', 'app/tg_bridge.py',
        'app/routes/artifacts.py', 'app/static/js/chat.js', 'app/model_catalog.py', 'app/usage_contract.py']
    manifest = []
    for filename in files:
        data = (ROOT / filename).read_bytes()
        manifest.append({'file': filename, 'sha256': hashlib.sha256(data).hexdigest()})
    (TASK / 'code-manifest.json').write_text(json.dumps(manifest, indent=2))
    urls = {
        'openai-vision.html': 'https://developers.openai.com/api/docs/guides/images-vision',
        'claude-vision.html': 'https://platform.claude.com/docs/en/build-with-claude/vision',
        'paddle-orientation.md': 'https://raw.githubusercontent.com/PaddlePaddle/PaddleOCR/main/docs/version3.x/module_usage/doc_img_orientation_classification.en.md',
        'rapid-readme.md': 'https://raw.githubusercontent.com/RapidAI/RapidOrientation/main/README.md',
        'rapid-main.py': 'https://raw.githubusercontent.com/RapidAI/RapidOrientation/main/rapid_orientation/main.py',
        'rapid-pypi.json': 'https://pypi.org/pypi/rapid-orientation/json',
        'openrouter-images.html': 'https://openrouter.ai/docs/features/multimodal/images',
    }
    sources = [fetch(name, url) for name, url in urls.items()]
    (TASK / 'sources' / 'manifest.json').write_text(json.dumps(sources, indent=2))
