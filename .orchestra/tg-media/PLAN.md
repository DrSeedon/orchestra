# TG Bridge — Media Support

## Context
Orchestra TG bridge currently accepts only text messages. Need full media support like kesha-tg-bot:
photos, documents, voice (Deepgram transcription), video, video notes (ffmpeg+transcription), stickers, audio.

## Reference implementation
`/mnt/data/Projects/Python/kesha-tg-bot/` — handlers.py, media.py, telegram_io.py.
Pattern: download → save to disk → pass file path to Claude as `[type: /path]` text tag.

## Phase 1 — Photos + Documents

### Files to change
- `app/tg_bridge.py` — add handlers for F.photo, F.document, F.video, F.audio, F.sticker

### Implementation
1. Add `download_media(bot, file_id, filename, file_unique_id)` function:
   - Cache by `file_unique_id` in `data/uploads/.media_cache.json`
   - If cached and file exists → return cached path
   - Otherwise `bot.download(file_id)` → save to `data/uploads/{filename}`
   - Return absolute path

2. Add handlers:
   - `F.photo` → download largest (`msg.photo[-1]`), format `[photo: /path] caption`
   - `F.document` → download, preserve original filename, format `[document: /path (original_name)]`
   - `F.video` → download, format `[video: /path] caption`
   - `F.audio` → download, preserve filename, format `[audio: /path (original_name)]`
   - `F.sticker` → no download, format `[sticker: emoji]`

3. Send to orchestrator via `manager.send(session.id, prompt)`

### Format to Claude (same as kesha)
```
[photo: /mnt/data/Projects/Python/orchestra/data/uploads/photo_20260509_1234_56789.jpg]
optional caption text here
```
Claude reads the file via Read tool — supports images natively.

## Phase 2 — Voice Messages (Deepgram)

### Dependencies
- `DEEPGRAM_API_KEY` in `.env`
- `aiohttp` (already installed via aiogram)

### Implementation
1. Add `transcribe(file_path, file_unique_id)` function:
   - Cache transcriptions in `data/uploads/.transcription_cache.json`
   - POST to `https://api.deepgram.com/v1/listen?model=nova-2&language=ru&smart_format=true`
   - Return `(text, error)`

2. Handler `F.voice`:
   - Download `.oga` file
   - If Deepgram key → transcribe → `[voice: /path | transcribed text]`
   - No key → `[voice: /path]` (Claude can't read audio)

## Phase 3 — Video Notes (ffmpeg + Deepgram)

### Dependencies
- `ffmpeg` system binary
- Deepgram API key

### Implementation
1. Handler `F.video_note`:
   - Download `.mp4`
   - Extract audio: `ffmpeg -i video.mp4 -vn -acodec libopus -y audio.oga`
   - Transcribe audio via Deepgram
   - Format: `[video_note: /path | transcribed text]`
   - Fallback (no ffmpeg/Deepgram): `[video_note: /path]`

## Shared utilities

### Media cache (from kesha media.py pattern)
```python
MEDIA_CACHE_PATH = UPLOADS_DIR / ".media_cache.json"

def _load_cache() -> dict: ...
def _save_cache(cache: dict): ...

async def download_media(bot, file_id, filename, file_unique_id) -> str:
    cache = _load_cache()
    if file_unique_id in cache and Path(cache[file_unique_id]).exists():
        return cache[file_unique_id]
    file = await bot.get_file(file_id)
    path = UPLOADS_DIR / filename
    await bot.download_file(file.file_path, path)
    cache[file_unique_id] = str(path)
    _save_cache(cache)
    return str(path)
```

### Prompt assembly (from kesha handlers.py pattern)
```
{forward_meta}{reply_meta}[type: /path] caption
```

## Edge cases
- File > 20MB → TG Bot API limit, skip with error message
- Deepgram rate limit → fallback to path-only
- ffmpeg not installed → fallback to path-only for video notes
- Media cleanup: reuse existing `data/uploads/` with md5 dedup from image paste feature

## Estimate
- Phase 1: ~80 lines in tg_bridge.py
- Phase 2: ~50 lines (transcribe function + handler)
- Phase 3: ~30 lines (ffmpeg + handler)
- Total: ~160 lines
