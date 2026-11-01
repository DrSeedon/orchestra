"""Retrieve public license evidence only; no install, inference or private data."""
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import urllib.error
import urllib.request
import zipfile

TASK = Path(__file__).resolve().parent
DEST = TASK / 'sources' / 'licenses'


def download(url):
    with urllib.request.urlopen(url, timeout=40) as response:
        return response.read()


def save(name, data, url, **extra):
    (DEST / name).write_bytes(data)
    row = {'file': name, 'url': url, 'bytes': len(data),
           'sha256': hashlib.sha256(data).hexdigest(), **extra}
    print(json.dumps(row, ensure_ascii=False))
    return row


def main():
    DEST.mkdir(exist_ok=True)
    rows = []
    url = 'https://pypi.org/pypi/rapid-orientation/0.0.11/json'
    data = download(url)
    rows.append(save('rapid-orientation-0.0.11-pypi.json', data, url))
    metadata = json.loads(data)
    assert metadata['info']['version'] == '0.0.11'
    print('rapid_license_metadata', metadata['info']['license'])
    wheel = next(row for row in metadata['urls'] if row['filename'].endswith('.whl'))
    package = download(wheel['url'])
    digest = hashlib.sha256(package).hexdigest()
    assert digest == wheel['digests']['sha256']
    print('wheel_sha256_verified', digest)
    with zipfile.ZipFile(BytesIO(package)) as archive:
        notices = [name for name in archive.namelist()
                   if Path(name).name.upper().startswith(('LICENSE', 'NOTICE', 'COPYING', 'AUTHORS'))]
        print('wheel_license_notice_members', json.dumps(notices))
        for name in notices:
            rows.append(save('rapid-0.0.11-' + Path(name).name, archive.read(name),
                             wheel['url'], archive_member=name, wheel_sha256=digest))
        # Keep the original package's license/author metadata, without reinstalling it.
        member = next(name for name in archive.namelist() if name.endswith('.dist-info/METADATA'))
        header = archive.read(member).split(b'\n\n', 1)[0] + b'\n'
        rows.append(save('rapid-0.0.11-METADATA-header.txt', header, wheel['url'],
                         archive_member=member, wheel_sha256=digest))
        # Confirm every versioned retained source remains byte-identical to the wheel.
        for local, member in {
            'rapid-0.0.11-main.py': 'rapid_orientation/main.py',
            'rapid-0.0.11-utils-preprocess.py': 'rapid_orientation/utils/preprocess.py',
            'rapid-0.0.11-utils-infer_engine.py': 'rapid_orientation/utils/infer_engine.py',
            'rapid-0.0.11-config.yaml': 'rapid_orientation/config.yaml',
        }.items():
            assert (TASK / 'sources' / local).read_bytes() == archive.read(member), local
        print('PASS: all four retained versioned Rapid sources match wheel bytes; notices unchanged')
    for project, url in {
        'RapidOrientation': 'https://raw.githubusercontent.com/RapidAI/RapidOrientation/main/LICENSE',
        'PaddleOCR': 'https://raw.githubusercontent.com/PaddlePaddle/PaddleOCR/main/LICENSE',
        'Tesseract': 'https://raw.githubusercontent.com/tesseract-ocr/tesseract/main/LICENSE',
    }.items():
        rows.append(save(project + '-LICENSE', download(url), url))
    notice_url = 'https://raw.githubusercontent.com/RapidAI/RapidOrientation/main/NOTICE'
    try:
        rows.append(save('RapidOrientation-NOTICE', download(notice_url), notice_url))
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        row = {'url': notice_url, 'status': 404, 'note': 'No root NOTICE at checked URL; original source headers retained.'}
        rows.append(row)
        print(json.dumps(row))
    (DEST / 'manifest.json').write_text(json.dumps({
        'fetched_at_utc': datetime.now(timezone.utc).isoformat(), 'sources': rows,
    }, indent=2))
    print('PASS: version-specific Rapid license retained; code-license primary sources saved; no install or inference')


if __name__ == '__main__':
    main()
