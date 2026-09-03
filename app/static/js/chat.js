// === Chat ===
// Optimistic UI: show message immediately, debounce actual send so rapid
// follow-up messages get batched. The server echoes back via SSE which
// replaces the bubble with the canonical version.
let pendingUserMsgs = [];
let pendingBubble = null;
let uiDebounceTimer = null;

async function sendChat() {
    const input = $('#chat-input');
    // Картинка ещё летит → ждём её путь, иначе сообщение уйдёт без картинки.
    // Поле ввода при этом живое: всё, что допечатают за время ожидания, войдёт в msg.
    if (_pendingUploads.size) {
        const btn = $('#send-btn');
        const label = btn.textContent;
        btn.textContent = '⏳';
        await Promise.allSettled([..._pendingUploads]);
        btn.textContent = label;
    }
    const msg = input.value.trim();
    if (!msg || !currentScope || !selectedAgent) return;
    input.value = '';
    clearPastePreview();

    pendingUserMsgs.push(msg);
    localMessages.add(msg);
    showPendingBubble();

    if (uiDebounceTimer) clearTimeout(uiDebounceTimer);
    uiDebounceTimer = setTimeout(() => finalizePending(), UI_DEBOUNCE_MS);

    try {
        await api(`/api/sessions/${selectedAgent}/send`, {
            method: 'POST',
            body: JSON.stringify({ message: msg, scope: currentScope }),
            signal: AbortSignal.timeout(15000),
        });
    } catch (e) {
        if (e.name === 'TimeoutError') return;
        if (uiDebounceTimer) { clearTimeout(uiDebounceTimer); uiDebounceTimer = null; }
        if (pendingBubble) { const ring = pendingBubble.querySelector('.debounce-ring'); if (ring) ring.remove(); }
        pendingBubble = null; pendingUserMsgs = []; _finalizedBubble = null;
        removeWaitingIndicator();
        // Перезапуск — штатная операция, и красная строка про неё выглядела бы аварией.
        addChatEntry(e.name === 'RestartPendingError' ? 'notification' : 'error', e.message);
    }
}

function showPendingBubble() {
    const chat = $('#chat');
    if (!pendingBubble) {
        pendingBubble = document.createElement('div');
        pendingBubble.className = 'chat-user ml-16 px-3 py-2 rounded-lg text-sm break-words';
        chat.appendChild(pendingBubble);
    }
    pendingBubble.textContent = pendingUserMsgs.join('\n');
    const oldRing = pendingBubble.querySelector('.debounce-ring');
    if (oldRing) oldRing.remove();
    const ring = document.createElement('span');
    ring.className = 'debounce-ring';
    pendingBubble.appendChild(ring);
    chat.scrollTop = chat.scrollHeight;
}

let _finalizedBubble = null;
function finalizePending() {
    if (!pendingBubble) return;
    const ring = pendingBubble.querySelector('.debounce-ring');
    if (ring) ring.remove();
    const combined = pendingUserMsgs.join('\n');
    localMessages.add(combined);
    _finalizedBubble = pendingBubble;
    pendingBubble = null;
    pendingUserMsgs = [];
    uiDebounceTimer = null;
    showWaitingIndicator();
}

const _VOICE_MAX_MS = 5 * 60 * 1000;
let _voiceRecorder = null;
let _voiceStream = null;
let _voiceAudioContext = null;
let _voiceAnalyser = null;
let _voiceFrame = 0;
let _voiceLastFrame = 0;
let _voiceSamples = null;
let _voiceStartedAt = 0;
let _voiceCancelled = false;
let _voiceStarting = false;
let _voiceStopping = false;

function _voiceMimeType() {
    const choices = [
        'audio/webm;codecs=opus',
        'audio/mp4;codecs=mp4a.40.2',
        'audio/mp4',
        'audio/webm',
        'audio/ogg;codecs=opus',
    ];
    return choices.find(type => MediaRecorder.isTypeSupported(type)) || '';
}

function _voiceSetState(state) {
    const controls = $('#voice-controls');
    if (!controls) return;
    controls.dataset.state = state;
    $('#voice-btn').disabled = state === 'processing' || state === 'requesting' || state === 'stopping';
    $('#voice-state-label').textContent = state === 'requesting'
        ? 'Микрофон…' : (state === 'stopping' ? 'Завершаю…' : 'Запись');
    $('#voice-cancel-btn').disabled = state !== 'recording';
}

function _showVoiceError(message) {
    const error = $('#voice-error');
    if (!error) return;
    error.textContent = message;
    error.classList.toggle('is-visible', Boolean(message));
}

function _voiceCaptureError(error) {
    if (!window.isSecureContext) return 'Микрофон доступен только через HTTPS.';
    if (error?.name === 'NotAllowedError') return 'Доступ к микрофону запрещён. Разрешите его в настройках браузера.';
    if (error?.name === 'NotFoundError') return 'Микрофон не найден.';
    if (error?.name === 'NotReadableError') return 'Микрофон занят другим приложением.';
    return `Не удалось включить микрофон: ${error?.name || 'Error'}: ${error?.message || error}`;
}

function _stopVoiceCapture() {
    cancelAnimationFrame(_voiceFrame);
    _voiceFrame = 0;
    _voiceAnalyser = null;
    _voiceSamples = null;
    if (_voiceAudioContext) _voiceAudioContext.close().catch(() => {});
    _voiceAudioContext = null;
    if (_voiceStream) _voiceStream.getTracks().forEach(track => track.stop());
    _voiceStream = null;
    $('#voice-level')?.style.setProperty('--voice-level', '1');
}

function _drawVoiceLevel(now) {
    if (!_voiceAnalyser || !_voiceRecorder || _voiceRecorder.state !== 'recording') return;
    if (now - _voiceLastFrame < 33) {
        _voiceFrame = requestAnimationFrame(_drawVoiceLevel);
        return;
    }
    _voiceLastFrame = now;
    _voiceAnalyser.getByteTimeDomainData(_voiceSamples);
    let energy = 0;
    for (const sample of _voiceSamples) {
        const centered = (sample - 128) / 128;
        energy += centered * centered;
    }
    const level = Math.min(1, Math.sqrt(energy / _voiceSamples.length) * 4);
    $('#voice-level')?.style.setProperty('--voice-level', (1 + level * 1.25).toFixed(2));
    const elapsed = now - _voiceStartedAt;
    const seconds = Math.floor(elapsed / 1000);
    $('#voice-timer').textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
    if (elapsed >= _VOICE_MAX_MS) {
        stopVoiceInput();
        return;
    }
    _voiceFrame = requestAnimationFrame(_drawVoiceLevel);
}

function _voiceExtension(mimeType) {
    if (mimeType.startsWith('audio/mp4')) return 'm4a';
    if (mimeType.startsWith('audio/ogg')) return 'ogg';
    return 'webm';
}

async function _sendVoiceBlob(blob, mimeType) {
    _voiceSetState('idle');
    const body = new FormData();
    body.append('audio', blob, `voice.${_voiceExtension(mimeType)}`);
    body.append('session_name', selectedAgent || '');
    body.append('scope', currentScope || '');
    try {
        body.append('send', 'true');
        const response = await fetch('/api/transcribe', {
            method: 'POST',
            body,
            signal: AbortSignal.timeout(60000),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.error || result.detail || `HTTP ${response.status}`);
        _showVoiceError('');
    } catch (error) {
        const detail = error.name === 'TimeoutError'
            ? 'Отправка голосового сообщения не ответила за 60 секунд.'
            : error.message;
        _showVoiceError(`Голосовой ввод: ${detail}`);
    } finally {
        _voiceSetState('idle');
    }
}

async function startVoiceInput() {
    if (_voiceRecorder?.state === 'recording') {
        stopVoiceInput();
        return;
    }
    if (_voiceStarting || _voiceStopping) return;
    _showVoiceError('');
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        _showVoiceError(window.isSecureContext
            ? 'Этот браузер не поддерживает запись с микрофона.'
            : 'Микрофон доступен только через HTTPS.');
        return;
    }
    _voiceStarting = true;
    _voiceSetState('requesting');
    try {
        _voiceStream = await navigator.mediaDevices.getUserMedia({audio: true});
        const mimeType = _voiceMimeType();
        const recorder = mimeType
            ? new MediaRecorder(_voiceStream, {mimeType, audioBitsPerSecond: 64000})
            : new MediaRecorder(_voiceStream);
        const chunks = [];
        _voiceRecorder = recorder;
        _voiceCancelled = false;
        recorder.addEventListener('dataavailable', event => {
            if (event.data.size) chunks.push(event.data);
        });
        recorder.addEventListener('error', event => {
            _showVoiceError(_voiceCaptureError(event.error));
            _voiceCancelled = true;
            _voiceStopping = true;
            if (recorder.state === 'recording') recorder.stop();
        });
        recorder.addEventListener('stop', () => {
            const cancelled = _voiceCancelled;
            const actualType = recorder.mimeType || mimeType || chunks[0]?.type || 'audio/webm';
            const blob = new Blob(chunks, {type: actualType});
            if (_voiceRecorder === recorder) _voiceRecorder = null;
            _voiceStopping = false;
            _stopVoiceCapture();
            if (cancelled) {
                _voiceSetState('idle');
                return;
            }
            if (!blob.size) {
                _showVoiceError('Голосовой ввод: браузер вернул пустую запись.');
                _voiceSetState('idle');
                return;
            }
            _sendVoiceBlob(blob, actualType);
        }, {once: true});

        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        _voiceAudioContext = new AudioContextClass();
        const source = _voiceAudioContext.createMediaStreamSource(_voiceStream);
        _voiceAnalyser = _voiceAudioContext.createAnalyser();
        _voiceAnalyser.fftSize = 256;
        _voiceSamples = new Uint8Array(_voiceAnalyser.fftSize);
        source.connect(_voiceAnalyser);
        _voiceStartedAt = performance.now();
        _voiceLastFrame = 0;
        $('#voice-timer').textContent = '0:00';
        _voiceStarting = false;
        _voiceSetState('recording');
        recorder.start();
        _voiceFrame = requestAnimationFrame(_drawVoiceLevel);
    } catch (error) {
        _voiceStarting = false;
        _stopVoiceCapture();
        _voiceRecorder = null;
        _voiceSetState('idle');
        _showVoiceError(_voiceCaptureError(error));
    }
}

function stopVoiceInput(cancel = false) {
    if (!_voiceRecorder || _voiceRecorder.state !== 'recording') return;
    _voiceCancelled = cancel;
    _voiceStopping = true;
    _voiceSetState('stopping');
    _voiceRecorder.stop();
}

function initVoiceInput() {
    const input = $('#chat-input');
    const actions = $('#send-btn')?.parentElement;
    if (!input || !actions || $('#voice-controls')) return;
    const controls = document.createElement('div');
    controls.id = 'voice-controls';
    controls.className = 'voice-controls';
    controls.dataset.state = 'idle';
    controls.innerHTML = `
        <button id="voice-btn" type="button" class="voice-button" title="Голосовой ввод" aria-label="Начать или остановить голосовой ввод">
            <span id="voice-level" class="voice-level"></span><span class="voice-icon">🎤</span>
        </button>
        <div class="voice-recording" aria-live="polite">
            <span id="voice-timer" class="voice-timer">0:00</span>
            <span id="voice-state-label">Запись</span>
            <button id="voice-cancel-btn" type="button" class="voice-cancel" title="Отменить запись" aria-label="Отменить запись">×</button>
        </div>`;
    input.parentElement.insertBefore(controls, actions);
    const error = document.createElement('div');
    error.id = 'voice-error';
    error.className = 'voice-error';
    error.setAttribute('role', 'alert');
    input.parentElement.after(error);
    $('#voice-btn').addEventListener('click', startVoiceInput);
    $('#voice-cancel-btn').addEventListener('click', () => stopVoiceInput(true));
    window.addEventListener('pagehide', () => stopVoiceInput(true));
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && _voiceRecorder?.state === 'recording') stopVoiceInput(true);
    });
}

function showWaitingIndicator() {
    removeWaitingIndicator();
    const chat = $('#chat');
    const wasAtBottom = _chatAtBottom(chat);
    const div = document.createElement('div');
    div.id = 'waiting-indicator';
    div.className = 'flex items-center gap-2 text-xs text-slate-500 py-2 px-3';
    div.innerHTML = '<span class="waiting-dots"><span>.</span><span>.</span><span>.</span></span> waiting for response';
    chat.appendChild(div);
    if (wasAtBottom) chat.scrollTop = chat.scrollHeight;
}

let pastedImages = [];
// Работа с файлом, которую sendChat обязан дождаться — вся, от сжатия до ответа
// сервера. Иначе сообщение уйдёт без картинки, а её путь допишется в уже пустое
// поле осиротевшей строкой. Регистрируем на верхнем уровне, по разу на файл.
const _pendingUploads = new Set();
function _trackUpload(promise) {
    _pendingUploads.add(promise);
    promise.finally(() => _pendingUploads.delete(promise));
    return promise;
}

// Одна дорога для paste и drop: ошибку показываем строкой над полем ввода,
// путь ДОПИСЫВАЕМ в textarea и только после ответа сервера. Трогать input.value
// во время загрузки нельзя — юзер в это время печатает, и его текст пропадёт.
async function _uploadToChat(file, filename, uploadCard = null) {
    const card = uploadCard || (typeof _showUploadingChip === 'function'
        ? _showUploadingChip(file, filename)
        : {updateProgress() {}, complete() {}, fail() {}});
    card.setFilename?.(filename);
    const promise = (async () => {
        const formData = new FormData();
        formData.append('file', file, filename);
        card.updateProgress(1);
        // fetch does not expose upload progress; XHR does, and its timeout keeps the
        // existing 60-second bound for a stalled connection.
        return await new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            card.abort = () => xhr.abort();
            xhr.open('POST', '/api/upload');
            xhr.timeout = 60000;
            xhr.upload.addEventListener('progress', event => {
                if (event.lengthComputable && event.total > 0) {
                    card.updateProgress((event.loaded / event.total) * 100);
                }
            });
            xhr.addEventListener('load', () => {
                let data = {};
                try { data = JSON.parse(xhr.responseText || '{}'); } catch {}
                if (xhr.status < 200 || xhr.status >= 300) {
                    reject(new Error(data.error || `HTTP ${xhr.status}`));
                    return;
                }
                if (!data.path) {
                    reject(new Error('server returned no file path'));
                    return;
                }
                resolve(data);
            });
            xhr.addEventListener('error', () => reject(new Error('network error')));
            xhr.addEventListener('abort', () => reject(new Error('upload aborted')));
            xhr.addEventListener('timeout', () => reject(new Error('upload timed out')));
            xhr.send(formData);
        });
    })();
    try {
        const data = await promise;
        if (card.cancelled) return null;
        card.complete(data.path, data.url || data.path);
        _insertPathAtCaret($('#chat-input'), data.path, data.url || data.path, false);
        return data;
    } catch (error) {
        if (card.cancelled) return null;
        card.fail(error);
        // У TimeoutError и сетевых ошибок message бывает пустой — печатаем и класс.
        // Дописываем к уже показанной ошибке: при дропе пачки файлов упасть может не один
        const detail = `${filename}: ${error.name}: ${error.message}`;
        const shown = $('#chat-drop-error')?.textContent;
        _showChatDropError(shown ? `${shown}; ${detail}` : `Upload failed — ${detail}`);
        return null;
    }
}

// Аплоад с машины юзера идёт на 53-82 КБ/с (замер оттуда же): типичный retina-скриншот
// 667 КБ ползёт 12 с, и это упирается в канал, а не в сервер — единственный способ
// ускорить — отправить меньше байтов. WebP q=0.9 даёт 354 КБ (1.9×) при PSNR 38.6 дБ:
// на кропе 1:1 текст неотличим от оригинала. Цифры — .orchestra/tasks/5/report.md.
// Только для вставки из буфера: дропнутый файл юзер выбрал сам, его формат не наш.
const _COMPRESS_MIN_BYTES = 100 * 1024;  // мельче — экономия секунды не стоит работы CPU

async function _compressScreenshot(file) {
    if (file.size < _COMPRESS_MIN_BYTES) return {blob: file, ext: 'png'};
    try {
        const bitmap = await createImageBitmap(file);
        const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
        canvas.getContext('2d').drawImage(bitmap, 0, 0);
        bitmap.close();
        const blob = await canvas.convertToBlob({type: 'image/webp', quality: 0.9});
        // Фото и мелкие картинки от WebP не выигрывают — тогда шлём как есть
        if (blob.size < file.size) return {blob, ext: 'webp'};
    } catch (error) {
        // Не ошибка юзера: файл всё равно уйдёт оригиналом, поэтому в консоль, не в UI
        console.warn('Screenshot compression skipped:', error.name, error.message);
    }
    return {blob: file, ext: 'png'};
}

async function handlePaste(e) {
    const items = e.clipboardData?.items;
    if (!items) return;
    for (const item of items) {
        if (!item.type.startsWith('image/')) continue;
        e.preventDefault();
        const file = item.getAsFile();
        if (!file) continue;
        _showChatDropError('');
        const pasteName = `paste-${Date.now()}`;
        const uploadCard = _showUploadingChip(file, `${pasteName}.png`);
        await _trackUpload((async () => {
            const {blob, ext} = await _compressScreenshot(file);
            if (uploadCard.cancelled) return;
            await _uploadToChat(blob, `${pasteName}.${ext}`, uploadCard);
        })());
        break;
    }
}

// Пока файл летит, показываем его же из памяти браузера — сеть для этого не нужна.
// Возвращает функцию снятия: сам узел + освобождение objectURL, чтобы не текла память.
function _showUploadingChip(file, filename = file.name || 'file') {
    let cardFilename = filename;
    const objectUrl = URL.createObjectURL(file);
    const container = _pastePreviewContainer();
    const wrap = document.createElement('div');
    wrap.className = 'upload-file-card relative';
    wrap.dataset.fileName = cardFilename;
    wrap.style.cssText = 'display:flex;align-items:center;gap:8px;padding:6px 8px;border:1px solid #334155;border-radius:6px;min-width:220px;max-width:100%;font-size:11px;color:#cbd5e1';
    const isImage = /\.(png|jpe?g|gif|webp|svg)$/i.test(cardFilename) || file.type.startsWith('image/');
    let preview = null;
    if (isImage) {
        const img = document.createElement('img');
        img.src = objectUrl;
        img.className = 'paste-preview-image rounded border border-slate-700';
        img.width = 64;
        img.height = 64;
        img.alt = cardFilename;
        wrap.appendChild(img);
        preview = img;
    } else {
        const icon = document.createElement('span');
        icon.textContent = '📄';
        icon.style.fontSize = '24px';
        wrap.appendChild(icon);
    }
    const body = document.createElement('div');
    body.style.cssText = 'display:flex;flex:1;min-width:0;flex-direction:column;gap:3px';
    const name = document.createElement('span');
    name.className = 'upload-file-name';
    name.textContent = cardFilename;
    name.style.cssText = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
    name.title = cardFilename;
    const size = document.createElement('span');
    size.textContent = _fmtKb(file.size);
    size.style.color = '#64748b';
    const download = document.createElement('a');
    download.href = objectUrl;
    download.download = cardFilename;
    download.textContent = '📥 скачать';
    download.style.cssText = 'color:#a5b4fc;text-decoration:none;width:max-content';
    const progress = document.createElement('progress');
    progress.className = 'upload-progress';
    progress.max = 100;
    progress.value = 0;
    progress.style.cssText = 'width:100%;height:5px';
    const progressText = document.createElement('span');
    progressText.className = 'upload-progress-text';
    progressText.textContent = 'Загрузка… 0%';
    progressText.style.cssText = 'font-size:10px;color:#818cf8';
    body.append(name, size, download, progress, progressText);
    wrap.appendChild(body);
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.textContent = '×';
    remove.title = 'Удалить файл';
    remove.style.cssText = 'align-self:flex-start;border:0;background:transparent;color:#94a3b8;cursor:pointer;font-size:16px;line-height:1';
    wrap.appendChild(remove);
    container.appendChild(wrap);
    const cleanup = () => {
        wrap.remove();
        URL.revokeObjectURL(objectUrl);
        if (!container.children.length) container.remove();
    };
    cleanup.cancelled = false;
    const removePath = () => {
        const path = wrap.dataset.filePath;
        if (!path) return;
        const input = $('#chat-input');
        input.value = input.value.split('\n').filter(line => line.trim() !== path.trim()).join('\n').trim();
        pastedImages = pastedImages.filter(url => url !== (wrap.dataset.fileUrl || path));
    };
    remove.addEventListener('click', () => {
        cleanup.cancelled = true;
        cleanup.abort?.();
        removePath();
        cleanup();
    });
    cleanup.updateProgress = percent => {
        const value = Math.max(0, Math.min(100, Number(percent) || 0));
        progress.value = value;
        progressText.textContent = `Загрузка… ${Math.round(value)}%`;
    };
    cleanup.setFilename = nextFilename => {
        cardFilename = String(nextFilename || cardFilename);
        wrap.dataset.fileName = cardFilename;
        name.textContent = cardFilename;
        name.title = cardFilename;
        download.download = cardFilename;
    };
    cleanup.complete = (path, url) => {
        wrap.dataset.filePath = path;
        wrap.dataset.fileUrl = url;
        download.href = url;
        download.download = cardFilename;
        if (preview) preview.src = url;
        progress.value = 100;
        progressText.textContent = 'Загружено';
        progressText.style.color = '#4ade80';
        URL.revokeObjectURL(objectUrl);
    };
    cleanup.fail = error => {
        progressText.textContent = `Ошибка: ${error.message || error}`;
        progressText.style.color = '#f87171';
    };
    return cleanup;
}

function _pastePreviewContainer() {
    let container = $('#paste-preview');
    if (!container) {
        container = document.createElement('div');
        container.id = 'paste-preview';
        container.className = 'flex flex-wrap gap-2 px-1 pb-1';
        const inputRow = $('#chat-input').parentElement;
        inputRow.parentElement.insertBefore(container, inputRow);
    }
    return container;
}

function showImagePreview(url, filePath) {
    const container = _pastePreviewContainer();
    const wrap = document.createElement('div');
    wrap.className = 'relative';
    wrap.dataset.url = url;
    wrap.dataset.filePath = filePath || url;
    const isImage = /\.(png|jpg|jpeg|gif|webp|svg)$/i.test(filePath || url);
    if (isImage) {
        const img = document.createElement('img');
        img.src = url;
        img.className = 'paste-preview-image rounded border border-slate-700';
        img.width = 64;
        img.height = 64;
        img.alt = (filePath || url).split('/').pop() || 'Image preview';
        img.loading = 'lazy';
        img.style.cursor = 'pointer';
        img.addEventListener('click', () => openFilePreview(filePath || url));
        wrap.appendChild(img);
    } else {
        const name = (filePath || url).split('/').pop();
        const chip = document.createElement('div');
        chip.className = 'flex items-center gap-1 px-2 py-1 rounded border border-slate-700 text-xs text-slate-400 cursor-pointer hover:border-indigo-500';
        chip.style.maxWidth = '180px';
        chip.innerHTML = `<span>📄</span><span class="truncate">${DOMPurify.sanitize(name)}</span>`;
        chip.addEventListener('click', () => openFilePreview(filePath || url));
        wrap.appendChild(chip);
    }
    const rm = document.createElement('button');
    rm.className = 'absolute -top-1 -right-1 bg-red-600 text-white rounded-full w-4 h-4 text-xs leading-none';
    rm.textContent = '×';
    rm.addEventListener('click', () => {
        wrap.remove();
        pastedImages = pastedImages.filter(u => u !== url);
        const input = $('#chat-input');
        const removePath = filePath || url;
        input.value = input.value.split('\n').filter(line => line.trim() !== removePath.trim()).join('\n').trim();
        if (!container.children.length) container.remove();
    });
    wrap.appendChild(rm);
    container.appendChild(wrap);
}

function clearPastePreview() {
    pastedImages = [];
    const el = $('#paste-preview');
    if (el) el.remove();
}


function renderImages(el, content) {
    const re = /(\/\S+\.(png|jpg|jpeg|gif|webp|svg))/gi;
    const matches = content.match(re);
    if (!matches) return;

    const imageUrl = (path, preview = false) =>
        `/api/files/raw?path=${encodeURIComponent(path)}${preview ? '&preview=640' : ''}`;
    const makeImage = (path, className = '', openOnClick = true) => {
        const img = document.createElement('img');
        img.src = imageUrl(path, true);
        img.loading = 'lazy';
        img.decoding = 'async';
        img.fetchPriority = 'low';
        img.className = className;
        if (openOnClick) {
            img.addEventListener('click', () => openImageLightbox(imageUrl(path)));
        }
        return img;
    };

    if (matches.length === 1) {
        const img = makeImage(matches[0], 'chat-inline-image');
        img.onerror = () => img.remove();
        el.appendChild(img);
        return;
    }

    const previewCount = 4;
    const gallery = document.createElement('section');
    gallery.className = 'chat-image-gallery';
    gallery.dataset.imageCount = String(matches.length);
    gallery.setAttribute('aria-label', `Галерея: ${matches.length} фото`);

    const header = document.createElement('div');
    header.className = 'chat-image-gallery-header';
    const count = document.createElement('span');
    count.className = 'chat-image-gallery-count';
    count.textContent = `📷 ${matches.length} фото`;
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'chat-image-gallery-toggle';
    toggle.hidden = matches.length <= previewCount;
    header.append(count, toggle);

    const grid = document.createElement('div');
    grid.className = 'chat-image-gallery-grid';

    const renderGallery = (expanded) => {
        gallery.classList.toggle('is-expanded', expanded);
        toggle.setAttribute('aria-expanded', String(expanded));
        toggle.textContent = expanded ? 'Свернуть' : `Показать все ${matches.length}`;
        grid.replaceChildren();
        const shown = expanded ? matches : matches.slice(0, previewCount);
        shown.forEach((path, index) => {
            const thumb = document.createElement('button');
            thumb.type = 'button';
            thumb.className = 'chat-image-gallery-thumb';
            thumb.setAttribute('aria-label', `Открыть фото ${index + 1} из ${matches.length}`);
            const img = makeImage(path, '', false);
            img.alt = `Фото ${index + 1} из ${matches.length}`;
            img.onerror = () => thumb.remove();
            thumb.appendChild(img);

            const hiddenCount = matches.length - previewCount;
            const expandsGallery = !expanded && index === previewCount - 1 && hiddenCount > 0;
            if (expandsGallery) {
                const more = document.createElement('span');
                more.className = 'chat-image-gallery-more';
                more.textContent = `+${hiddenCount}`;
                thumb.appendChild(more);
                thumb.setAttribute('aria-label', `Показать остальные ${hiddenCount} фото`);
            }
            thumb.addEventListener('click', () => {
                if (expandsGallery) renderGallery(true);
                else openImageLightbox(imageUrl(path));
            });
            grid.appendChild(thumb);
        });
    };

    toggle.addEventListener('click', () => {
        renderGallery(!gallery.classList.contains('is-expanded'));
    });
    gallery.append(header, grid);
    renderGallery(false);
    el.appendChild(gallery);
}

function removeWaitingIndicator() {
    const el = $('#waiting-indicator');
    if (el) el.remove();
}

async function stopAgent() {
    if (!selectedAgent || !currentScope) return;
    try {
        await api(`/api/sessions/${selectedAgent}/interrupt`, {
            method: 'POST',
            body: JSON.stringify({ scope: currentScope }),
        });
    } catch {}
}

function updateStopButton(status) {
    const btn = $('#stop-btn');
    if (status === 'running') {
        btn.classList.remove('hidden');
    } else {
        btn.classList.add('hidden');
    }
}

function _showImageOverlay(src) {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.9);display:flex;align-items:center;justify-content:center;z-index:9999;cursor:pointer';
    const bigImg = document.createElement('img');
    bigImg.src = src;
    bigImg.style.cssText = 'max-width:90vw;max-height:90vh;object-fit:contain';
    overlay.appendChild(bigImg);
    overlay.addEventListener('click', () => overlay.remove());
    document.addEventListener('keydown', function esc(e) { if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', esc); } });
    document.body.appendChild(overlay);
}

function addTimestamp(el, ts) {
    if (!el || !ts || el.querySelector('.chat-time')) return;
    const d = new Date(ts);
    const local = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const time = document.createElement('span');
    time.className = 'chat-time';
    time.textContent = local;
    el.appendChild(time);
}

function addCopyBtn(el, text) {
    if (!el || el.querySelector('.copy-btn')) return;
    el.style.position = 'relative';
    const btn = document.createElement('button');
    btn.className = 'copy-btn';
    btn.textContent = '📋';
    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        // navigator.clipboard requires HTTPS — fallback for HTTP
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(text);
        } else {
            const ta = document.createElement('textarea');
            ta.value = text; ta.style.cssText = 'position:fixed;left:-9999px';
            document.body.appendChild(ta); ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
        }
        btn.textContent = '✅';
        setTimeout(() => btn.textContent = '📋', 1500);
    });
    el.appendChild(btn);
}

let streamBubble = null;
let streamContent = '';
let streamPending = '';
let _streamRafId = null;
let _streamLastParse = 0;
let _streamDeferredFinal = null;
// Last text that closed a live stream bubble. Grok (and any async log writer) can deliver
// `turn ended` status before the matching `text` row; if we already finalized the stream,
// a second identical `text` must not paint a second bubble.
let _lastFinalizedStreamText = '';
const _STREAM_BASE_CPS = 12;  // chars per frame at 60fps (~720 chars/sec)
const _STREAM_PARSE_INTERVAL = 50;  // ms between marked.parse calls

const _UNEXECUTED_TOOL_CALL_WARNING = 'НЕ ВЫПОЛНЕНО — похоже на вызов инструмента, напечатанный текстом';

// Cross-runtime duplicate of app/tool_call_guard.py: browser JS cannot import the Python helper.
function _looksLikeUnexecutedToolCall(text) {
    const prose = String(text || '')
        .replace(/(```|~~~)[\s\S]*?(?:\1|$)/g, '')
        .replace(/`[^`\n]*`/g, '');
    const signals = [
        /<invoke\s+name\s*=/i,
        /<\/invoke\s*>/i,
        /<parameter\s+name\s*=/i,
        /<\/parameter\s*>/i,
        /<function_calls(?:\s[^>]*)?>/i,
    ];
    return signals.filter(pattern => pattern.test(prose)).length >= 2;
}

function _unexecutedToolCallWarningHtml(content) {
    if (!_looksLikeUnexecutedToolCall(content)) return '';
    return `<div class="codex-warning unexecuted-tool-call-warning"><span class="codex-warning-icon">⚠</span><span>${_UNEXECUTED_TOOL_CALL_WARNING}</span></div>`;
}

function _markUnexecutedToolCall(container, content) {
    const oldWarning = container.querySelector(':scope > .unexecuted-tool-call-warning');
    if (!_looksLikeUnexecutedToolCall(content)) {
        if (oldWarning) oldWarning.remove();
        return;
    }
    if (oldWarning) return;
    const warning = document.createElement('div');
    warning.className = 'codex-warning unexecuted-tool-call-warning';
    warning.innerHTML = '<span class="codex-warning-icon">⚠</span><span></span>';
    warning.lastChild.textContent = _UNEXECUTED_TOOL_CALL_WARNING;
    container.prepend(warning);
}

function _selectionTouchesStream() {
    if (!streamBubble?.isConnected) return false;
    const selection = window.getSelection();
    return !!selection && !selection.isCollapsed && selection.rangeCount > 0
        && selection.getRangeAt(0).intersectsNode(streamBubble);
}

function _finalizeStreamBubble(finalText, ts) {
    streamBubble.classList.remove('streaming');
    streamBubble.innerHTML = DOMPurify.sanitize(marked.parse(finalText));
    _markUnexecutedToolCall(streamBubble, finalText);
    addCopyBtn(streamBubble, finalText);
    addTimestamp(streamBubble, ts);
    streamBubble.dataset.chatTimelineType = 'text';
    if (typeof _recomputeChatTimelineFinals === 'function') _recomputeChatTimelineFinals();
    if (typeof _syncChatTimelineControls === 'function') _syncChatTimelineControls();
    _lastFinalizedStreamText = finalText || '';
    streamBubble = null;
    streamContent = '';
    streamPending = '';
    _streamDeferredFinal = null;
}

function _completeStreamBubble(content, ts) {
    _streamFlush();
    const finalText = content || streamContent;
    if (_selectionTouchesStream()) {
        _streamDeferredFinal = { finalText, ts };
        return;
    }
    _finalizeStreamBubble(finalText, ts);
}

function _resumeStreamAfterSelection() {
    if (_selectionTouchesStream()) return;
    if (_streamDeferredFinal) {
        const deferred = _streamDeferredFinal;
        _streamDeferredFinal = null;
        _finalizeStreamBubble(deferred.finalText, deferred.ts);
    } else if (streamPending && !_streamRafId) {
        _streamRafId = requestAnimationFrame(_streamRenderTick);
    }
}

document.addEventListener('selectionchange', _resumeStreamAfterSelection);

function _streamRenderTick() {
    _streamRafId = null;
    if (!streamBubble || !streamPending) return;
    if (_selectionTouchesStream()) return;
    const chat = $('#chat');
    const wasAtBottom = _chatAtBottom(chat);
    // Adaptive speed: if buffer is growing, accelerate to not fall behind
    const chunkSize = Math.max(_STREAM_BASE_CPS, Math.floor(streamPending.length / 8));
    const chunk = streamPending.slice(0, chunkSize);
    streamPending = streamPending.slice(chunkSize);
    streamContent += chunk;
    const now = performance.now();
    const sinceLastParse = now - _streamLastParse;
    if (sinceLastParse >= _STREAM_PARSE_INTERVAL || !streamPending) {
        _streamLastParse = now;
        streamBubble.innerHTML = DOMPurify.sanitize(marked.parse(streamContent));
    }
    _markUnexecutedToolCall(streamBubble, streamContent);
    // Typing cursor — remove stale one before adding
    const oldCur = streamBubble.querySelector('.typing-cursor');
    if (oldCur) oldCur.remove();
    const lastEl = streamBubble.querySelector(':scope > :last-child') || streamBubble;
    const cur = document.createElement('span');
    cur.className = 'typing-cursor';
    cur.textContent = '▍';
    lastEl.appendChild(cur);
    if (wasAtBottom) chat.scrollTo({ top: chat.scrollHeight, behavior: 'smooth' });
    else _markChatHasNewBelow();
    if (streamPending) _streamRafId = requestAnimationFrame(_streamRenderTick);
}

function _streamFlush() {
    if (_streamRafId) { cancelAnimationFrame(_streamRafId); _streamRafId = null; }
    if (streamPending) {
        streamContent += streamPending;
        streamPending = '';
    }
}

function _renderJsonGrid(obj, container, maxDepth) {
    if (maxDepth === undefined) maxDepth = 2;
    const grid = document.createElement('div');
    grid.style.cssText = 'display:grid;grid-template-columns:auto 1fr;gap:1px 10px;font-size:10px;align-items:baseline';
    const entries = Object.entries(obj);
    for (const [key, val] of entries) {
        if (key === 'system_prompt' || key === 'error_trace' || key === '_codex_item_id') continue;
        const keyEl = document.createElement('span');
        keyEl.style.cssText = 'color:#64748b;white-space:nowrap;font-family:monospace';
        keyEl.textContent = key;
        grid.appendChild(keyEl);
        const valEl = document.createElement('span');
        valEl.style.cssText = 'overflow:hidden;text-overflow:ellipsis;overflow-wrap:anywhere;min-width:0';
        if (val === null || val === undefined) {
            valEl.textContent = 'null';
            valEl.style.color = '#6b7280';
        } else if (typeof val === 'boolean') {
            valEl.textContent = String(val);
            valEl.style.color = val ? '#22c55e' : '#ef4444';
        } else if (typeof val === 'number') {
            valEl.textContent = String(val);
            valEl.style.color = '#eab308';
        } else if (typeof val === 'string') {
            const MAX_STR = 150;
            const short = val.length > MAX_STR ? val.slice(0, MAX_STR) + '…' : val;
            valEl.textContent = short;
            valEl.style.color = '#cbd5e1';
            if (val.length > MAX_STR) {
                valEl.style.cursor = 'pointer';
                valEl.title = 'Click to expand';
                let _strExp = false;
                valEl.addEventListener('click', (e) => {
                    e.stopPropagation();
                    _strExp = !_strExp;
                    valEl.textContent = _strExp ? val : short;
                });
            }
        } else if (Array.isArray(val)) {
            if (val.length === 0) {
                valEl.textContent = '[]';
                valEl.style.color = '#6b7280';
            } else if (val.every(v => typeof v === 'string' || typeof v === 'number')) {
                const arrStr = val.join(', ');
                valEl.textContent = arrStr.length > 120 ? arrStr.slice(0, 120) + '…' : arrStr;
                valEl.style.color = '#cbd5e1';
            } else {
                valEl.textContent = `[${val.length} items]`;
                valEl.style.color = '#38bdf8';
                valEl.style.cursor = 'pointer';
                let _arrExp = false;
                valEl.addEventListener('click', (e) => {
                    e.stopPropagation();
                    _arrExp = !_arrExp;
                    if (_arrExp) {
                        valEl.textContent = '';
                        const pre = document.createElement('pre');
                        pre.style.cssText = 'font-size:10px;color:#94a3b8;margin:0;white-space:pre-wrap;overflow-wrap:anywhere;max-height:200px;overflow-y:auto';
                        pre.textContent = JSON.stringify(val, null, 2);
                        valEl.appendChild(pre);
                    } else {
                        valEl.textContent = `[${val.length} items]`;
                    }
                });
            }
        } else if (typeof val === 'object' && maxDepth > 0) {
            const subKeys = Object.keys(val);
            if (subKeys.length <= 4) {
                const sub = document.createElement('div');
                _renderJsonGrid(val, sub, maxDepth - 1);
                valEl.textContent = '';
                valEl.appendChild(sub);
            } else {
                valEl.textContent = `{${subKeys.length} keys}`;
                valEl.style.color = '#38bdf8';
                valEl.style.cursor = 'pointer';
                let _objExp = false;
                valEl.addEventListener('click', (e) => {
                    e.stopPropagation();
                    _objExp = !_objExp;
                    if (_objExp) {
                        valEl.textContent = '';
                        const pre = document.createElement('pre');
                        pre.style.cssText = 'font-size:10px;color:#94a3b8;margin:0;white-space:pre-wrap;overflow-wrap:anywhere;max-height:200px;overflow-y:auto';
                        pre.textContent = JSON.stringify(val, null, 2);
                        valEl.appendChild(pre);
                    } else {
                        valEl.textContent = `{${subKeys.length} keys}`;
                    }
                });
            }
        } else {
            valEl.textContent = JSON.stringify(val);
            valEl.style.color = '#94a3b8';
        }
        grid.appendChild(valEl);
    }
    container.appendChild(grid);
    return grid;
}

function _runFanSummary(data) {
    const tasks = Array.isArray(data?.tasks) ? data.tasks : [];
    const reuse = Array.isArray(data?.reuse) ? data.reuse : [];
    const total = tasks.length + reuse.length;
    const count = `${total} ${total === 1 ? 'воркер' : total < 5 ? 'воркера' : 'воркеров'}`;
    const seconds = Number(data?.deadline_seconds);
    let deadline = 'без дедлайна';
    if (Number.isFinite(seconds) && seconds > 0) {
        const minutes = Math.round(seconds / 60);
        deadline = minutes >= 60
            ? `${Math.floor(minutes / 60)} ч${minutes % 60 ? ` ${minutes % 60} мин` : ''}`
            : `${minutes} мин`;
    }
    return `🎼 run_fan → ${count} · дедлайн ${deadline}`;
}

function _runFanItems(data) {
    const tasks = Array.isArray(data?.tasks) ? data.tasks : [];
    const reuse = Array.isArray(data?.reuse) ? data.reuse : [];
    return [
        ...tasks.map(item => ({
            name: item?.name || '?',
            model: item?.model || '',
            role: item?.role || 'worker',
        })),
        ...reuse.map(item => ({
            name: item?.name || '?',
            model: '',
            role: 'reuse',
        })),
    ];
}

function buildCompactToolLine(type, content, ts, payload) {
    const line = document.createElement('div');
    line.className = 'flex items-center gap-2 text-xs py-0.5 px-2 cursor-pointer rounded group';
    line.style.color = '#64748b';

    if (type === 'tool') {
        const colonIdx = content.indexOf(':');
        const rawName = canonicalToolName(colonIdx > 0 ? content.slice(0, colonIdx).trim() : content.slice(0, 30));
        const body = colonIdx > 0 ? content.slice(colonIdx + 1).trim() : '';
        let icon = toolIcon(rawName);
        const short = toolShortName(rawName);

        let preview = body;
        const _safeTaskFilter = (value) => typeof value === 'string' && value.length <= 32 && !/[<>\"'`]/.test(value);
        const _taskListFilter = (parsedObj) => {
            const parts = [parsedObj.status, parsedObj.project, parsedObj.assignee]
                .map((value) => (typeof value === 'string' ? value.trim() : ''))
                .filter((value) => value && _safeTaskFilter(value));
            return parts.length > 0 ? parts.join(', ') : '';
        };
        try {
            const parsed = JSON.parse(body);
            if (rawName === NOTIFY_USER_TOOL) preview = `🔔 ${parsed.reason || 'зовёт'}`;
            else if (rawName === 'mcp__orchestra__spawn_worker') {
                icon = '👶';
                const role = parsed.role ? ` · ${parsed.role}` : '';
                const task = parsed.task_id ? ` · #${taskNum(parsed.task_id)}` : '';
                preview = `→ ${parsed.name || '?'} · ${_modelLabel(parsed.model || 'claude-sonnet-4-6')}${role}${task}`;
            }
            else if (rawName === 'mcp__orchestra__send_message') {
                icon = '✉️';
                const message = typeof parsed.message === 'string' ? parsed.message : '';
                preview = `→ ${parsed.to || '?'} · ${message.length} симв.`;
            }
            else if (rawName === 'mcp__orchestra__task_create') {
                icon = '📋';
                const priority = parsed.priority != null ? ` · приоритет ${parsed.priority}` : '';
                preview = `создаёт задачу «${typeof parsed.title === 'string' ? parsed.title : '?'}»${priority}`;
            }
            else if (rawName === 'mcp__orchestra__task_update') {
                icon = '✏️';
                const status = typeof parsed.status === 'string' && parsed.status ? ` • статус ${parsed.status}` : '';
                preview = `обновляет задачу #${taskNum(parsed.par) || '?'}${status}`;
            }
            else if (rawName === 'mcp__orchestra__run_fan') {
                preview = _runFanSummary(parsed).replace(/^🎼 run_fan → /, '→ ');
            }
            else if (rawName === 'mcp__websearch__search' || rawName === 'mcp__websearch__search_web' || rawName === 'WebSearch') preview = codexWebSearchCompactLabel(codexWebSearchSpec(parsed));
            else if (rawName === 'ToolSearch') preview = `🔍 ${parsed.query || ''}`;
            else if (rawName === 'mcp__orchestra__report_bug') preview = `🐛 ${parsed.title || '?'}`;
            else if (rawName === 'mcp__orchestra__send_file') preview = `📎 ${(parsed.path || '').split('/').pop() || '?'}`;
            else if (rawName === 'mcp__orchestra__send_files') {
                const paths = Array.isArray(parsed.paths) ? parsed.paths : [];
                preview = `📎 ${paths.length} files`;
            }
            else if (rawName === 'mcp__orchestra__kill_worker') preview = `💀 Kill: ${parsed.name || '?'}`;
            else if (rawName === 'mcp__orchestra__stop_worker') preview = `⏸️ Stop: ${parsed.name || '?'}`;
            else if (rawName === 'mcp__orchestra__get_worker_logs') preview = `📋 Logs: ${parsed.name || '?'} (${parsed.limit || 20})`;
            else if (rawName === 'mcp__orchestra__get_worker_info') preview = `🤖 Info: ${parsed.name || '?'}`;
            else if (rawName === 'mcp__orchestra__list_agents') preview = '🎼 Agents';
            else if (rawName === 'mcp__orchestra__list_orchestrators') preview = '🎯 Orchestrators';
            else if (rawName === 'mcp__orchestra__compact_worker') preview = `🗜 Compact: ${parsed.name || '?'}`;
            else if (rawName === 'mcp__orchestra__rename_worker') preview = `✏️ ${parsed.old_name || '?'} → ${parsed.new_name || '?'}`;
            else if (rawName === 'mcp__orchestra__change_worker_model') preview = `🔄 ${parsed.name || '?'} → ${parsed.model || '?'}`;
            else if (rawName === 'mcp__orchestra__update_worker_description') preview = `✏️ ${parsed.name || '?'} — description`;
            else if (rawName === 'mcp__orchestra__merge_worker') preview = `🔀 Merge: ${parsed.name || '?'}`;
            else if (rawName === 'Glob') preview = `🔎 ${parsed.pattern || '?'}`;
            else if (rawName === 'TodoWrite') {
                const _tds = Array.isArray(parsed.todos) ? parsed.todos : [];
                const _dn = _tds.filter(t => t.status === 'completed').length;
                const _cur = _tds.find(t => t.status === 'in_progress');
                preview = `📝 ${_dn}/${_tds.length} todos${_cur ? ' · ' + String(_cur.content || '').slice(0, 40) : ''}`;
            }
            else if (rawName === 'Review') preview = `🧠 ${(parsed.focus || 'review').slice(0, 60)}`;
            else if (rawName === 'Skill') preview = `⚡ ${parsed.skill || '?'}`;
            else if (rawName === 'FileChange') {
                const changes = parsed.changes || [];
                preview = `📝 ${changes.length} file${changes.length === 1 ? '' : 's'}`;
            }
            else if (rawName === 'ViewImage') preview = `🖼 ${(parsed.file_path || '').split('/').pop() || 'image'}`;
            else if (rawName === 'ImageGeneration') preview = '🎨 generating image';
            else if (rawName === 'Sleep') preview = `⏱ ${Math.round((parsed.duration_ms || 0) / 1000)}s`;
            else if (rawName === 'mcp__orchestra__task_list') {
                const _fl = _taskListFilter(parsed);
                preview = `читает список задач${_fl ? ` (${_fl})` : ''}`;
            } else if (rawName === 'mcp__orchestra__task_get') preview = `читает задачу #${taskNum(parsed.par) || '?'}`;
            else if (rawName === 'mcp__orchestra__bg_create') { const _bi = _JOB_ICONS[parsed.type]||'⚙️'; preview = `${_bi} BG: ${parsed.type||'?'} ${parsed.message ? '"'+parsed.message.slice(0,30)+'"' : ''}`; }
            else if (rawName === 'mcp__orchestra__bg_list') preview = '📊 BG Jobs';
            else if (rawName === 'mcp__orchestra__bg_cancel') preview = `⏹ Cancel job ${(parsed.job_id||'').slice(0,8)}`;
            else if (rawName === 'WebFetch' || rawName === 'mcp__websearch__web_fetch') { let _d = '?'; try { _d = new URL(parsed.url).hostname; } catch {} preview = `🌐 ${_d}`; }
            else if (parsed.file_path) preview = parsed.file_path.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '') + (parsed.offset ? ` :${parsed.offset}` : '') + (parsed.limit ? ` (${parsed.limit} lines)` : '');
            else if (parsed.command) preview = parsed.command;
            else if (parsed.pattern) preview = parsed.pattern;
            else if (parsed.path) preview = parsed.path;
            else if (parsed.message) preview = parsed.message;
            else if (parsed.content) preview = parsed.content.slice(0, 80);
            else preview = body.slice(0, 80);
        } catch {
            preview = rawName === 'WebSearch'
                ? `🌐 "${body.slice(0, 120)}"`
                : body.slice(0, 120);
        }

        const isOrch = rawName.startsWith('mcp__orchestra__');
        const nameColor = isOrch ? '#a78bfa' : '#38bdf8';

        const iconSpan = document.createElement('span');
        iconSpan.textContent = icon;
        iconSpan.style.minWidth = '1.2em';

        const nameSpan = document.createElement('span');
        nameSpan.textContent = short;
        nameSpan.style.color = nameColor;
        nameSpan.style.minWidth = 'max-content';

        let desc = '';
        try { desc = JSON.parse(body).description || ''; } catch {}

        const descSpan = document.createElement('span');
        descSpan.className = 'shrink-0';
        descSpan.style.color = '#64748b';
        descSpan.textContent = desc ? `— ${desc}` : '';

        const previewSpan = document.createElement('span');
        previewSpan.className = 'truncate flex-1 opacity-60 compact-preview';
        previewSpan.textContent = preview;

        const resultSpan = document.createElement('span');
        resultSpan.className = 'compact-result shrink-0';
        resultSpan.style.color = '#475569';

        line.append(iconSpan, nameSpan, descSpan, previewSpan, resultSpan);
        line.dataset.compactTool = '1';
        line.dataset.toolContent = content;
        line.dataset.toolRaw = rawName;
        if (rawName === NOTIFY_USER_TOOL) {
            line.classList.add('chat-notify-user');
            line.style.color = '#fca5a5';
        }
        if (payload?.tool_use_id) line.dataset.toolUseId = payload.tool_use_id;
        try {
            const parsed = JSON.parse(body);
            if (parsed._codex_item_id && !line.dataset.toolUseId) {
                line.dataset.toolUseId = parsed._codex_item_id;
                _flushCodexToolUpdates(line, parsed._codex_item_id);
            }
        } catch {}

        line.addEventListener('mouseenter', () => line.style.backgroundColor = 'rgba(30,41,59,0.5)');
        line.addEventListener('mouseleave', () => line.style.backgroundColor = '');

        let fullBubble = null;
        line.addEventListener('click', () => {
            if (fullBubble) {
                fullBubble.remove();
                fullBubble = null;
                return;
            }
            fullBubble = document.createElement('div');
            fullBubble.className = 'ml-4 mb-1';
            const tempContent = line.dataset.toolContent;
            const tempResult = line.dataset.resultContent || '';
            const savedCompact = window.compactMode;
            window.compactMode = false;
            const anchor = line.nextSibling;
            const chat = $('#chat');
            const sentinel = document.createElement('span');
            sentinel.style.display = 'none';
            if (anchor) chat.insertBefore(sentinel, anchor);
            else chat.appendChild(sentinel);
            const toolPayload = line.dataset.toolUseId
                ? {tool_use_id: line.dataset.toolUseId}
                : undefined;
            addChatEntry('tool', tempContent, null, sentinel, toolPayload);
            if (tempResult) {
                addChatEntry('tool_result', tempResult, null, sentinel, toolPayload);
            }
            window.compactMode = savedCompact;
            const rendered = [];
            let node = line.nextSibling;
            while (node && node !== sentinel) {
                rendered.push(node);
                node = node.nextSibling;
            }
            sentinel.remove();
            for (const el of rendered) {
                el.remove();
                fullBubble.appendChild(el);
            }
            line.after(fullBubble);
        });
    } else {
        line.dataset.unmatchedToolResult = '1';
        line.style.color = '#f59e0b';
        const toolUseId = payload?.tool_use_id;
        if (toolUseId) {
            line.dataset.orphanResultFor = toolUseId;
            line._orphanResult = {content, ts, payload};
        }
        line.textContent = `⚠️ Результат без вызова${toolUseId ? ` · ${toolUseId}` : ''} — ${content.slice(0, 100)}`;
    }

    return line;
}

function _findLastBefore(parent, selector, anchor) {
    let node = anchor ? anchor.previousElementSibling : parent.lastElementChild;
    while (node) {
        if (node.matches(selector)) return node;
        node = node.previousElementSibling;
    }
    return null;
}

// У результата без tool_use_id связать его с вызовом можно только соседством: поле
// появилось недавно, и 63.7% строк журнала (все до него) идентификатора не несут.
// Точный поиск для них означал бы «Результат без вызова» на КАЖДОЙ старой строке.
function _toolForResult(chat, payload, anchor, compact) {
    const toolUseId = payload?.tool_use_id;
    if (!toolUseId) return _findLastBefore(chat, compact ? '[data-compact-tool]' : '[data-last-tool]', anchor);
    // Идентификатор уникален, поэтому ищем по всему чату, а не назад от якоря: страница
    // истории разрезает параллельный блок, и вызов приезжает ПОЗЖЕ своего результата;
    // у Codex вызов и вовсе попадает в журнал после него.
    const idSelector = `[data-tool-use-id="${CSS.escape(String(toolUseId))}"]`;
    return chat.querySelector(compact
        ? `${idSelector}[data-compact-tool]`
        : `${idSelector}:not([data-compact-tool])`);
}

// Вызова ещё не было в DOM, когда рисовался результат — он стал сиротой. Как только
// вызов появился, забираем сироту к нему: перерисовываем результат на прежнем месте.
function _adoptOrphanResults(chat, toolUseId) {
    if (!toolUseId) return;
    const selector = `[data-orphan-result-for="${CSS.escape(String(toolUseId))}"]`;
    for (const node of [...chat.querySelectorAll(selector)]) {
        const saved = node._orphanResult;
        if (!saved) continue;
        // Узел НЕ удаляем: он может быть якорем текущей пачки истории или load-more;
        // удаление роняет вставку следующей строки
        // с NotFoundError. Гасим его и перерисовываем результат ровно на его месте.
        delete node.dataset.orphanResultFor;
        delete node.dataset.unmatchedToolResult;
        node._orphanResult = null;
        node.textContent = '';
        node.style.display = 'none';
        addChatEntry('tool_result', saved.content, saved.ts, node, saved.payload);
    }
}

const HIDE_THINKING = document.body.dataset.hideThinking === 'true';

// SDK stream events can beat TaskStarted by a few milliseconds. Buffer those
// lines by parent tool id, then move them into the task-id card once it exists.
const _pendingSubagentLogs = new Map();
function appendSubagentLog(subId, evType, content) {
    const chat = $('#chat');
    const host = chat.querySelector(`[data-subagent-id="${CSS.escape(subId)}"]`);
    if (!host) {
        if (!_pendingSubagentLogs.has(subId) && _pendingSubagentLogs.size >= 50) {
            _pendingSubagentLogs.delete(_pendingSubagentLogs.keys().next().value);
        }
        const pending = _pendingSubagentLogs.get(subId) || [];
        pending.push([evType, content]);
        if (pending.length > 100) pending.shift();
        _pendingSubagentLogs.set(subId, pending);
        return;
    }
    const body = host.querySelector('.sa-body');
    if (!body) return;
    if (evType === 'stream') {
        // Coalesce contiguous stream text into one line (typewriter feel)
        let last = body.lastElementChild;
        if (last && last.classList.contains('sa-stream')) {
            last.textContent += content;
        } else {
            last = document.createElement('div');
            last.className = 'sa-stream';
            last.textContent = content;
            body.appendChild(last);
        }
    } else {
        const line = document.createElement('div');
        const icon = evType === 'tool_use' ? '🔧' : evType === 'tool_result' ? '↳' : evType === 'thinking' ? '💭' : '';
        line.style.cssText = 'margin-top:2px;color:' + (evType === 'tool_use' ? '#c4b5fd' : '#94a3b8');
        const short = content.length > 300 ? content.slice(0, 300) + '…' : content;
        line.textContent = `${icon} ${short}`;
        body.appendChild(line);
    }
    body.scrollTop = body.scrollHeight;
}

function _flushPendingSubagentLogs(sourceId, targetId) {
    if (!sourceId || !targetId) return;
    const pending = _pendingSubagentLogs.get(sourceId);
    if (!pending) return;
    _pendingSubagentLogs.delete(sourceId);
    for (const [evType, content] of pending) {
        appendSubagentLog(targetId, evType, content);
    }
}

let _codexThinkingLive = null;
let _codexThinkingKey = '';
let _codexTurnDiffBubble = null;
const _pendingCodexToolUpdates = new Map();

function _resetCodexActivityState() {
    _removeCodexThinkingLive();
    _codexTurnDiffBubble = null;
    _pendingCodexToolUpdates.clear();
}

function resetChatTransientState() {
    localMessages.clear();
    pendingUserMsgs = [];
    pendingBubble = null;
    _finalizedBubble = null;
    if (uiDebounceTimer) clearTimeout(uiDebounceTimer);
    uiDebounceTimer = null;
    if (_streamRafId) cancelAnimationFrame(_streamRafId);
    _streamRafId = null;
    streamBubble = null;
    streamContent = '';
    streamPending = '';
    _streamDeferredFinal = null;
    _lastFinalizedStreamText = '';
    _resetCodexActivityState();
}

function _removeCodexThinkingLive(activity) {
    if (!_codexThinkingLive) return;
    if (activity && _codexThinkingLive.dataset.activity !== activity) return;
    _codexThinkingLive.remove();
    _codexThinkingLive = null;
    _codexThinkingKey = '';
}

function _codexToolHost(chat, payload, anchor) {
    const itemId = payload && payload.tool_use_id;
    if (itemId) {
        const exact = chat.querySelector(`[data-tool-use-id="${CSS.escape(itemId)}"]`);
        if (exact) return exact;
    }
    return _findLastBefore(chat, '[data-last-tool], [data-compact-tool]', anchor);
}

function _applyCodexToolUpdate(host, type, content) {
    if (!host) return;
    if (type === 'tool_patch') {
        const patch = renderCodexFileChange(content);
        if (!patch) return;
        const old = host.querySelector('.codex-file-change');
        if (old) old.replaceWith(patch);
        else host.appendChild(patch);
        return;
    }
    if (host.dataset.compactTool) {
        const result = host.querySelector('.compact-result');
        if (result) {
            const lastLine = String(content).trim().split('\n').pop() || 'working';
            result.textContent = `⚡ ${lastLine.slice(0, 42)}`;
            result.style.color = '#38bdf8';
        }
        return;
    }
    let pre = host.querySelector('.codex-live-output');
    if (!pre) {
        pre = document.createElement('pre');
        pre.className = 'codex-live-output';
        host.appendChild(pre);
    }
    const prefix = type === 'tool_stream' && host.dataset.toolStream === 'stdin' ? '› ' : '';
    pre.textContent = (pre.textContent + prefix + content).slice(-20_000);
    pre.scrollTop = pre.scrollHeight;
}

function _queueOrApplyCodexToolUpdate(chat, type, content, payload, anchor) {
    const host = _codexToolHost(chat, payload, anchor);
    const itemId = payload && payload.tool_use_id;
    if (host) {
        if (itemId) host.dataset.toolUseId = itemId;
        if (payload && payload.stream) host.dataset.toolStream = payload.stream;
        _applyCodexToolUpdate(host, type, content);
        return;
    }
    if (!itemId) return;
    const pending = _pendingCodexToolUpdates.get(itemId) || [];
    pending.push([type, content, payload || {}]);
    if (pending.length > 100) pending.shift();
    _pendingCodexToolUpdates.set(itemId, pending);
}

function _flushCodexToolUpdates(host, itemId) {
    if (!host || !itemId) return;
    const pending = _pendingCodexToolUpdates.get(itemId);
    if (!pending) return;
    _pendingCodexToolUpdates.delete(itemId);
    for (const [type, content, payload] of pending) {
        if (payload.stream) host.dataset.toolStream = payload.stream;
        _applyCodexToolUpdate(host, type, content);
    }
}

function _imageGenerationProjection(data) {
    return {
        status: String(data?.status || ''),
        saved_path: String(data?.saved_path || ''),
        revised_prompt: String(data?.revised_prompt || ''),
    };
}

function _completeImageGenerationTool(host, data) {
    const projected = _imageGenerationProjection(data);
    const header = host.querySelector('.flex.items-center');
    const failed = projected.status === 'failed';
    if (header) {
        header.textContent = failed ? '❌ Image generation failed' : '✅ Image generated';
        header.style.color = failed ? '#f87171' : '#f472b6';
    }
    host.querySelectorAll('.codex-tool-image, .codex-image-prompt').forEach(el => el.remove());
    if (projected.saved_path) {
        const img = document.createElement('img');
        img.src = `/api/files/raw?path=${encodeURIComponent(projected.saved_path)}&t=${Date.now()}`;
        img.loading = 'lazy';
        img.className = 'codex-tool-image';
        img.addEventListener('click', () => openImageLightbox(img.src));
        host.appendChild(img);
    }
    if (projected.revised_prompt) {
        const prompt = document.createElement('div');
        prompt.className = 'codex-image-prompt';
        prompt.textContent = projected.revised_prompt;
        host.appendChild(prompt);
    }
    return projected;
}

async function _restoreImageGenerationResult(host, payload) {
    const logId = Number(payload?.id);
    if (!host || !Number.isFinite(logId) || host.dataset.imageRestore === 'loading') return;
    host.dataset.imageRestore = 'loading';
    const header = host.querySelector('.flex.items-center');
    if (header) header.textContent = '↻ Restoring generated image';
    try {
        const row = await api(`/api/logs/${logId}`);
        const data = JSON.parse(row.content || '{}');
        const projected = _imageGenerationProjection(data);
        if (host.isConnected) _completeImageGenerationTool(host, projected);
    } catch (error) {
        if (host.isConnected && header) {
            header.textContent = `❌ Image unavailable · ${error.name}`;
            header.style.color = '#f87171';
        }
    } finally {
        delete host.dataset.imageRestore;
    }
}

function _renderCodexThinking(content, label) {
    const card = document.createElement('div');
    card.className = 'codex-activity-card codex-thinking-card';
    const header = document.createElement('button');
    header.className = 'codex-activity-header';
    header.innerHTML = `<span class="codex-activity-caret">▶</span><span>${label || 'Reasoning'}</span>`;
    const body = document.createElement('div');
    body.className = 'codex-activity-body markdown-body';
    body.innerHTML = DOMPurify.sanitize(marked.parse(content || ''));
    body.style.display = 'none';
    header.addEventListener('click', () => {
        const expanded = body.style.display !== 'none';
        body.style.display = expanded ? 'none' : 'block';
        header.querySelector('.codex-activity-caret').textContent = expanded ? '▶' : '▼';
    });
    card.append(header, body);
    return card;
}

function _renderCodexPlan(content) {
    let data;
    try { data = JSON.parse(content); } catch { data = {explanation: '', plan: []}; }
    const card = document.createElement('div');
    card.className = 'codex-activity-card codex-plan-card';
    const title = document.createElement('div');
    title.className = 'codex-plan-title';
    title.textContent = '▦ Plan';
    card.appendChild(title);
    if (data.explanation) {
        const explanation = document.createElement('div');
        explanation.className = 'codex-plan-explanation';
        explanation.textContent = data.explanation;
        card.appendChild(explanation);
    }
    const steps = document.createElement('div');
    steps.className = 'codex-plan-steps';
    for (const step of data.plan || []) {
        const row = document.createElement('div');
        const status = String(step.status || 'pending');
        row.className = `codex-plan-step codex-plan-${status.toLowerCase()}`;
        const icon = status === 'completed' ? '✓' : status === 'inProgress' ? '●' : '○';
        row.innerHTML = `<span class="codex-plan-icon">${icon}</span><span></span>`;
        row.lastChild.textContent = step.step || '';
        steps.appendChild(row);
    }
    card.appendChild(steps);
    return card;
}

const _TASK_PRIORITY_META = {
    0: ['🔴', 'Critical'],
    1: ['🟠', 'High'],
    2: ['🟡', 'Medium'],
    3: ['🟢', 'Low'],
};

function _taskMoney(value) {
    if (value == null || value === '') return '';
    if (typeof value === 'number') {
        return String(Math.abs(value)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
    }
    return DOMPurify.sanitize(String(value));
}

function _taskDescriptionHtml(description) {
    const text = String(description || '');
    if (!text) return '';
    const collapsible = text.length > 180 || text.split('\n').length > 3;
    const bodyStyle = collapsible ? 'max-height:64px;overflow:hidden' : '';
    const button = collapsible
        ? '<button type="button" data-task-description-toggle onclick="event.stopPropagation();_toggleTaskDescription(this)" style="margin-top:3px;padding:0;border:0;background:none;color:#818cf8;font-size:10px;cursor:pointer">▼ Развернуть</button>'
        : '';
    return `<div data-task-description style="margin-top:6px;border-top:1px solid rgba(51,65,85,0.55);padding-top:5px">
        <div style="font-size:9px;color:#64748b;margin-bottom:2px">DESCRIPTION</div>
        <div data-task-description-body class="markdown-body text-xs" style="${bodyStyle};overflow-wrap:anywhere;line-height:1.4;color:#94a3b8">${DOMPurify.sanitize(marked.parse(text))}</div>
        ${button}
    </div>`;
}

function _toggleTaskDescription(button) {
    const body = button.parentElement.querySelector('[data-task-description-body]');
    if (!body) return;
    const expanded = button.dataset.expanded === '1';
    button.dataset.expanded = expanded ? '0' : '1';
    body.style.maxHeight = expanded ? '64px' : 'none';
    body.style.overflow = expanded ? 'hidden' : 'visible';
    button.textContent = expanded ? '▼ Развернуть' : '▲ Свернуть';
}

function _taskCardBodyHtml(task) {
    const rows = [];
    const safe = (value) => DOMPurify.sanitize(String(value));
    const statusColor = {'done':'#22c55e','paid':'#22c55e','in_progress':'#38bdf8','new':'#e2e8f0','cancelled':'#ef4444'}[task.status] || '#e2e8f0';
    if (task.status) rows.push(`<div><span style="color:#64748b">Status:</span> <b style="color:${statusColor}">${safe(task.status)}</b></div>`);
    if (task.project) rows.push(`<div><span style="color:#64748b">Project:</span> <span style="color:#94a3b8">${safe(task.project)}</span></div>`);
    const price = task.price_rub ?? task.price;
    if (Number(price) > 0) rows.push(`<div><span style="color:#64748b">Price:</span> <b style="color:#eab308">${_taskMoney(price)} ${CUR}</b></div>`);
    if (task.assignee) rows.push(`<div><span style="color:#64748b">Assignee:</span> ${safe(task.assignee)}</div>`);
    if (task.priority != null && _TASK_PRIORITY_META[task.priority]) {
        const [icon, label] = _TASK_PRIORITY_META[task.priority];
        rows.push(`<div><span style="color:#64748b">Priority:</span> ${icon} ${label}</div>`);
    }
    const taskId = task.task_id ?? task.id;
    if (taskId != null && taskId !== '') rows.push(`<div><span style="color:#64748b">Task ID:</span> <span style="font-family:monospace">${safe(taskId)}</span></div>`);
    if (task.created_at) rows.push(`<div><span style="color:#64748b">Created:</span> ${safe(String(task.created_at).slice(0, 10))}</div>`);
    if (task.updated_at) rows.push(`<div><span style="color:#64748b">Updated:</span> ${safe(String(task.updated_at).slice(0, 10))}</div>`);
    if (task.completed_at) rows.push(`<div><span style="color:#64748b">Done:</span> ${safe(String(task.completed_at).slice(0, 10))}</div>`);
    if (task.paid_at) rows.push(`<div><span style="color:#64748b">Paid at:</span> ${safe(String(task.paid_at).slice(0, 10))}</div>`);
    const fields = rows.length
        ? `<div data-task-fields style="display:grid;grid-template-columns:1fr 1fr;gap:2px 8px;font-size:10px;color:#94a3b8">${rows.join('')}</div>`
        : '';
    return fields + _taskDescriptionHtml(task.description);
}

function _attachTaskRows(host, container, total, preview, expandedDisplay) {
    host.appendChild(container);
    if (total <= preview) return;
    const hint = document.createElement('div');
    hint.className = 'text-xs mt-1';
    hint.style.cssText = 'color:#a78bfa;cursor:pointer;text-align:center';
    let expanded = false;
    const render = () => {
        container.querySelectorAll('[data-task-row]').forEach((row, index) => {
            if (index >= preview) row.style.display = expanded ? expandedDisplay : 'none';
        });
        hint.textContent = expanded ? '▲ collapse' : `▼ ${total - preview} more`;
    };
    host.style.cursor = 'pointer';
    host.addEventListener('click', event => {
        if (event.target.tagName === 'A') return;
        expanded = !expanded;
        render();
    });
    render();
    host.appendChild(hint);
}

function _appendCaption(host, caption) {
    if (!caption) return;
    const element = document.createElement('div');
    element.className = 'text-xs';
    element.style.cssText = 'margin-top:2px;color:#cbd5e1';
    element.textContent = caption;
    host.appendChild(element);
}

function _diffContextLine(line) {
    const row = document.createElement('div');
    row.className = 'diff-line diff-line-ctx';
    const gutter = document.createElement('span');
    gutter.className = 'diff-gutter';
    gutter.textContent = ' ';
    const code = document.createElement('span');
    code.className = 'diff-code';
    code.textContent = line;
    row.append(gutter, code);
    return row;
}

function _appendToolTechnicalDetails(card, content) {
    const details = document.createElement('details');
    details.dataset.toolTechnicalDetails = '1';
    details.style.cssText = 'margin-top:6px;border-top:1px solid rgba(51,65,85,0.55);padding-top:4px';
    const summary = document.createElement('summary');
    summary.style.cssText = 'font-size:10px;color:#64748b;cursor:pointer;user-select:none';
    summary.textContent = 'Технические детали';
    details.addEventListener('click', event => event.stopPropagation());
    const raw = document.createElement('pre');
    raw.style.cssText = 'margin:5px 0 0;padding:6px 8px;border-radius:6px;background:#0d1117;color:#64748b;font-size:10px;white-space:pre-wrap;overflow-wrap:anywhere;max-height:220px;overflow:auto';
    try { raw.textContent = JSON.stringify(JSON.parse(content), null, 2); }
    catch { raw.textContent = content; }
    details.append(summary, raw);
    card.appendChild(details);
}

function _appendArgumentField(host, key, value) {
    const field = document.createElement('div');
    field.className = 'tool-argument-field';
    const label = document.createElement('div');
    label.className = 'tool-argument-label';
    label.textContent = key;
    const text = document.createElement('pre');
    text.className = 'tool-argument-value';
    text.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
    field.append(label, text);
    host.appendChild(field);
}

function _appendFullToolArguments(card, rawName, data) {
    const details = document.createElement('details');
    details.dataset.toolFullArguments = '1';
    details.className = 'tool-full-details';
    const summary = document.createElement('summary');
    summary.textContent = 'Полные аргументы';
    details.appendChild(summary);
    details.addEventListener('click', event => event.stopPropagation());

    if (rawName === 'mcp__orchestra__run_fan') {
        const tasks = Array.isArray(data?.tasks) ? data.tasks : [];
        const reuse = Array.isArray(data?.reuse) ? data.reuse : [];
        const settings = document.createElement('div');
        settings.className = 'tool-argument-settings';
        for (const [key, value] of Object.entries(data || {})) {
            if (key !== 'tasks' && key !== 'reuse') _appendArgumentField(settings, key, value);
        }
        details.appendChild(settings);
        for (const item of [...tasks, ...reuse]) {
            const worker = document.createElement('section');
            worker.className = 'run-fan-detail';
            const title = document.createElement('h4');
            title.textContent = `${item?.name || '?'}${item?.model ? ` · ${item.model}` : ''}${item?.role ? ` · ${item.role}` : ''}`;
            worker.appendChild(title);
            for (const [key, value] of Object.entries(item || {})) {
                if (key === 'task') {
                    const task = document.createElement('pre');
                    task.className = 'run-fan-task';
                    task.textContent = String(value || '');
                    worker.append(task);
                } else if (key === 'owned_dirs' && Array.isArray(value)) {
                    const dirs = document.createElement('ul');
                    dirs.className = 'run-fan-owned-dirs';
                    for (const dir of value) {
                        const li = document.createElement('li');
                        li.textContent = String(dir);
                        dirs.appendChild(li);
                    }
                    worker.append(dirs);
                } else if (!['name', 'model', 'role'].includes(key)) {
                    _appendArgumentField(worker, key, value);
                }
            }
            details.appendChild(worker);
        }
    } else {
        const settings = document.createElement('div');
        settings.className = 'tool-argument-settings';
        for (const [key, value] of Object.entries(data || {})) {
            _appendArgumentField(settings, key, value);
        }
        details.appendChild(settings);
    }
    card.appendChild(details);
}

function _agentResultSummary(content) {
    const lines = content.split('\n').filter(line => line.includes('|'));
    if (!lines.length) return null;
    const agents = lines.map(line => {
        const parts = line.split('|').map(part => part.trim());
        return {
            line,
            name: (parts[0] || '').replace(/\*\*/g, '').replace(/^[^\p{L}\p{N}_-]*/u, '').trim(),
            status: parts[1] || 'unknown',
        };
    });
    const counts = {running: 0, waiting: 0, broken: 0};
    for (const agent of agents) {
        if (Object.hasOwn(counts, agent.status)) counts[agent.status] += 1;
    }
    return {lines, agents, counts};
}

function _agentCountText(counts) {
    const word = (count, one, many) => `${count} ${count === 1 ? one : many}`;
    return [
        word(counts.running, 'работает', 'работают'),
        word(counts.waiting, 'ждёт', 'ждут'),
        word(counts.broken, 'сломан', 'сломаны'),
    ];
}

// Platform notices (`system`) and Codex `warning` share one look: otherwise `system`
// falls through to `.chat-bot` and a delivery failure reads as an agent reply (#51).
function renderSystemChatEntry(type, content, ts) {
    if (type !== 'system' && type !== 'warning') return null;
    const el = document.createElement('div');
    el.className = 'codex-warning';
    if (type === 'system') el.dataset.chatSystem = '1';
    const icon = document.createElement('span');
    icon.className = 'codex-warning-icon';
    icon.textContent = '⚠';
    const body = document.createElement('span');
    body.textContent = content;
    el.append(icon, body);
    addTimestamp(el, ts);
    return el;
}

const COMPACT_EDIT_TOOLS = new Set(['Edit', 'MultiEdit', 'Write']);
const COMPACT_TASK_TOOLS = new Set([
    'mcp__orchestra__task_create',
    'mcp__orchestra__task_get',
    'mcp__orchestra__task_update',
    'mcp__orchestra__task_list',
]);
const COMPACT_AGENT_LIST_TOOLS = new Set([
    'mcp__orchestra__list_agents',
    'mcp__orchestra__list_orchestrators',
]);
const COMPACT_ORCHESTRA_ACK_TOOLS = new Set([
    'mcp__orchestra__kill_worker',
    'mcp__orchestra__stop_worker',
    'mcp__orchestra__rename_worker',
    'mcp__orchestra__change_worker_model',
    'mcp__orchestra__update_worker_description',
    'mcp__orchestra__merge_worker',
    'mcp__orchestra__bg_create',
]);
const COMPACT_ORCHESTRA_SIMPLE_TOOLS = new Set([
    ...COMPACT_ORCHESTRA_ACK_TOOLS,
    'mcp__orchestra__compact_worker',
    'mcp__orchestra__send_message',
    'mcp__orchestra__get_worker_logs',
    'mcp__orchestra__get_worker_info',
    'mcp__orchestra__bg_cancel',
]);

function _updateCompactToolResult(card, content, isBase64Image) {
    const resultSpan = card.querySelector('.compact-result');
    if (isBase64Image) {
        if (resultSpan) resultSpan.textContent = '🖼 image';
        card.dataset.resultContent = '[image]';
        return;
    }

    const clean = content.replace(/^\{?"?result"?:\s*"?|"?\}?$/g, '').replace(/\\n/g, '\n');
    const rawName = card.dataset.toolRaw || '';
    const isTask = COMPACT_TASK_TOOLS.has(rawName);
    const isAgentList = COMPACT_AGENT_LIST_TOOLS.has(rawName);
    if (!resultSpan) {
        card.dataset.resultContent = (isTask || isAgentList) ? content : clean;
        return;
    }

    if (isTask) {
        let parsed = null;
        try { parsed = JSON.parse(content); } catch {}
        if (!parsed || parsed.error) {
            resultSpan.textContent = '❌';
        } else if (rawName === 'mcp__orchestra__task_create') {
            const number = taskNum(parsed.par ?? parsed.task_id ?? parsed.id) || '?';
            resultSpan.textContent = `✅ задача #${number} создана`;
        } else if (rawName === 'mcp__orchestra__task_get') {
            const number = taskNum(parsed.par ?? parsed.task_id ?? parsed.id) || '?';
            resultSpan.textContent = `📋 читает задачу #${number}`;
        } else if (rawName === 'mcp__orchestra__task_list') {
            resultSpan.textContent = `📋 читает список задач (${(parsed.tasks || []).length})`;
        } else {
            const number = taskNum(parsed.par ?? parsed.task_id ?? parsed.id) || '?';
            const status = parsed.new_status || parsed.status;
            resultSpan.textContent = `✏️ обновляет задачу #${number}${typeof status === 'string' && status ? ` • ${status}` : ''}`;
        }
    } else if (isAgentList) {
        const summary = _agentResultSummary(clean);
        if (summary) {
            resultSpan.textContent = `${summary.agents.length} всего · ${_agentCountText(summary.counts).join(' · ')}`;
            resultSpan.style.color = summary.counts.broken ? '#ef4444' : summary.counts.waiting ? '#f59e0b' : '#64748b';
        } else {
            resultSpan.textContent = '❌ нет списка';
        }
    } else if (rawName === 'mcp__orchestra__send_file') {
        resultSpan.textContent = clean.includes('error') ? '❌' : '✅ sent';
    } else if (rawName === 'mcp__orchestra__send_files') {
        const info = _sendFilesResultInfo(content);
        resultSpan.textContent = info.hasError ? '❌' : `✅ ${info.count} sent`;
    } else if (COMPACT_ORCHESTRA_SIMPLE_TOOLS.has(rawName)) {
        const hasError = /error|fail/i.test(clean);
        if (COMPACT_ORCHESTRA_ACK_TOOLS.has(rawName)) resultSpan.textContent = hasError ? '❌' : '✅';
        else if (rawName === 'mcp__orchestra__send_message') {
            const recipient = clean.match(/sent to '(.+?)'/i);
            resultSpan.textContent = hasError ? '❌' : recipient ? `✅ → ${recipient[1]}` : '✅';
        } else if (rawName === 'mcp__orchestra__bg_cancel') {
            resultSpan.textContent = hasError ? '❌' : '⏹';
        } else if (rawName === 'mcp__orchestra__compact_worker') {
            const percentage = clean.match(/(\d+)%/);
            resultSpan.textContent = percentage ? `✅ ${percentage[1]}%` : '✅';
        } else if (rawName === 'mcp__orchestra__get_worker_info') {
            try {
                const worker = JSON.parse(clean);
                const status = worker.status === 'running' ? '🟢' : worker.status === 'idle' ? '🟡' : '⚪';
                resultSpan.textContent = `${status} ${worker.name || '?'}`;
            } catch {
                resultSpan.textContent = '✅';
            }
        } else {
            resultSpan.textContent = `📎 ${clean.split('\n').filter(line => line.trim()).length} items`;
        }
    } else if (rawName === 'Glob') {
        resultSpan.textContent = `📎 ${clean.split('\n').filter(line => line.trim()).length} files`;
    } else if (rawName === 'Skill') {
        resultSpan.textContent = clean.includes('error') ? '❌' : '✅';
    } else if (rawName === 'WebFetch' || rawName === 'mcp__websearch__web_fetch') {
        const singleLine = clean.replace(/\n/g, ' ');
        resultSpan.textContent = '📎 ' + (singleLine.length > 40 ? singleLine.slice(0, 40) + '…' : singleLine);
    } else if (rawName === 'mcp__orchestra__report_bug') {
        resultSpan.textContent = '✅ reported';
    } else if (rawName === 'ToolSearch') {
        let toolName = '';
        try { toolName = JSON.parse(content).tool_name || ''; } catch {}
        if (!toolName) toolName = clean.match(/tool_name['":\s]+(\w+)/)?.[1] || '';
        resultSpan.textContent = toolName ? `✅ ${toolName}` : '✅ loaded';
    } else if (['mcp__websearch__search', 'mcp__websearch__search_web', 'WebSearch'].includes(rawName)) {
        const spec = codexWebSearchSpec(content);
        const preview = card.querySelector('.compact-preview');
        if (preview && spec) preview.textContent = codexWebSearchCompactLabel(spec);
        resultSpan.textContent = spec?.queries.length ? `✅ ${spec.queries.length} queries` : '✅';
    } else if (rawName === 'mcp__orchestra__spawn_worker') {
        resultSpan.textContent = clean.toLowerCase().includes('error') ? '❌' : '✅ spawned';
    } else if (COMPACT_EDIT_TOOLS.has(rawName)) {
        resultSpan.textContent = '📎 updated';
    } else if (rawName === 'Read') {
        let readShort = 'OK';
        try {
            const colon = card.dataset.toolContent.indexOf(':');
            const args = colon > 0 ? card.dataset.toolContent.slice(colon + 1).trim() : '';
            const filePath = JSON.parse(args).file_path;
            if (filePath) readShort = filePath.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '') || filePath;
        } catch {}
        resultSpan.textContent = '📖 ' + readShort;
    } else {
        const singleLine = clean.replace(/\n/g, ' ');
        resultSpan.textContent = '📎 ' + (singleLine.length > 40 ? singleLine.slice(0, 40) + '…' : singleLine);
    }
    card.dataset.resultContent = (isTask || isAgentList) ? content : clean;
}

function _renderCompactToolEntry(type, content, ts, payload, chat, anchor, insertAndFollow, isBase64Image) {
    if (!window.compactMode || (type !== 'tool' && type !== 'tool_result')) return false;
    if (type === 'tool_result') {
        const card = _toolForResult(chat, payload, anchor, true);
        if (card) {
            _updateCompactToolResult(card, content, isBase64Image);
            return true;
        }
    }

    const line = buildCompactToolLine(type, content, ts, payload);
    insertAndFollow(line, () => {
        _trimChatNodes(chat);
        if (type === 'tool') _adoptOrphanResults(chat, line.dataset.toolUseId);
    });
    return true;
}

function _renderStatusEntry(type, content, ts, anchor, insertAndFollow, payload) {
    if (type !== 'status') return false;
    if (payload?.status_hidden === true) return true;
    // A status row may beat the authoritative `text` row through async logging.
    // Never finalize streamBubble here or the later text becomes a duplicate answer.
    if (content?.startsWith('precompact timer')) return true;
    if (/^codex hook .+: (?:running|started|completed)(?: · \d+ms)?$/i.test(content || '')) return true;
    if (/^codex mcp .+: (?:starting|ready)$/i.test(content || '')) return true;
    if (/^compact started \(native Codex,/i.test(content || '')) return true;

    if (/^grok mcp ready\b/i.test(content || '')) {
        const badge = document.createElement('div');
        badge.className = 'text-center text-xs py-1 text-emerald-400 italic';
        badge.textContent = `🔌 ${content}`;
        addTimestamp(badge, ts);
        insertAndFollow(badge);
        return true;
    }

    const nativeCodexCompact = (content || '').match(
        /^compact done \(native Codex\):\s*(\d+)%\s*→\s*(\d+)%/i
    );
    const rateLimit = _parseRateLimitStatus(content);
    const codexReconnect = content.startsWith('codex reconnecting:');
    const codexSteer = content === 'message steered into active Codex turn';
    const codexReroute = content.startsWith('model rerouted:');
    const codexHook = content.startsWith('codex hook ');
    const codexMcp = content.startsWith('codex mcp ');
    const codexCompaction = content.includes('codex context compact');
    const badge = document.createElement('div');
    if (rateLimit) {
        if (!anchor && !scrollAfterLoad) {
            _showRateLimitBanner(selectedAgent, rateLimit.retry, rateLimit.max, rateLimit.delay);
        }
        badge.className = 'text-center text-xs py-1 text-amber-400 italic';
        badge.textContent = `⏳ Rate limit — Anthropic временно ограничил запросы, повтор ${rateLimit.retry}/${rateLimit.max} через ${rateLimit.delay}с (это НЕ твой лимит подписки)`;
    } else if (codexReconnect) {
        badge.className = 'text-center text-xs py-1 text-amber-400 italic';
        badge.textContent = `🔌 Codex reconnecting — ${content.slice('codex reconnecting:'.length).trim()}`;
    } else if (codexSteer) {
        badge.className = 'text-center text-xs py-1 text-cyan-400 italic';
        badge.textContent = '↪ Message steered into the current Codex turn';
    } else if (codexReroute) {
        badge.className = 'text-center text-xs py-1 text-fuchsia-400 italic';
        badge.textContent = `⇄ Codex model rerouted — ${content.slice('model rerouted:'.length).trim()}`;
    } else if (codexHook) {
        badge.className = 'text-center text-xs py-1 text-sky-400 italic';
        badge.textContent = `⌁ ${content}`;
    } else if (codexMcp) {
        badge.className = 'text-center text-xs py-1 text-emerald-400 italic';
        badge.textContent = `🔌 ${content}`;
    } else if (nativeCodexCompact) {
        badge.className = 'text-center text-xs py-1 text-amber-300 italic';
        badge.textContent = `🗜 Codex context compacted natively · ${nativeCodexCompact[1]}% → ${nativeCodexCompact[2]}% · same thread`;
    } else if (codexCompaction) {
        badge.className = 'text-center text-xs py-1 text-amber-300 italic';
        badge.textContent = '🗜 Codex context compacted';
    } else {
        badge.className = 'text-center text-xs py-1 text-slate-500 italic';
        badge.textContent = `⚡ ${content}`;
    }
    addTimestamp(badge, ts);
    insertAndFollow(badge);
    return true;
}

const SUBAGENT_LIFECYCLE_TYPES = new Set([
    'subagent_start',
    'subagent_end',
    'subagent_progress',
]);

// Часы живой фоновой задачи. Единственный владелец интервала — сам узел: таймер
// снимается и при финише (`_stopSubagentClock`), и при исчезновении узла из DOM, иначе
// обрезка чата по MAX_CHAT_NODES оставила бы вечно тикающие таймеры на удалённых баблах.
const _SA_CLOCK_TICK_MS = 1000;

function _formatSubagentElapsed(seconds) {
    const total = Math.max(0, Math.floor(seconds));
    const mins = Math.floor(total / 60);
    return mins ? `${mins}:${String(total % 60).padStart(2, '0')}` : `${total}s`;
}

function _startSubagentClock(element, ts) {
    const started = ts ? new Date(ts).getTime() : Date.now();
    const base = Number.isFinite(started) ? started : Date.now();
    const clock = document.createElement('span');
    clock.className = 'sa-clock';
    clock.style.cssText = 'margin-left:6px;color:#a78bfa;font-size:10px;font-variant-numeric:tabular-nums';
    element.appendChild(clock);
    const tick = () => {
        if (!element.isConnected) return _stopSubagentClock(element);
        clock.textContent = `⏳ идёт ${_formatSubagentElapsed((Date.now() - base) / 1000)}`;
    };
    tick();
    element._saClockId = setInterval(tick, _SA_CLOCK_TICK_MS);
}

function _stopSubagentClock(element) {
    if (element?._saClockId) {
        clearInterval(element._saClockId);
        element._saClockId = null;
    }
    element?.querySelector?.('.sa-clock')?.remove();
}

function _renderSubagentLifecycleEntry(type, content, ts, payload, chat, insertAndFollow) {
    if (!SUBAGENT_LIFECYCLE_TYPES.has(type)) return false;
    const parts = content.split('|').map(part => part.trim());
    const meta = {};
    const textParts = [];
    for (const part of parts) {
        const separator = part.indexOf('=');
        if (separator > 0 && /^\w+$/.test(part.slice(0, separator))) {
            meta[part.slice(0, separator)] = part.slice(separator + 1);
        } else if (part) {
            textParts.push(part);
        }
    }
    const description = textParts[0] || textParts[1] || '';
    const subagentId = payload?.subagent_id || meta.id || '';
    const isBackground = meta.type === 'local_bash';
    const element = document.createElement('div');
    element.style.cssText = 'font-size:11px;padding:4px 10px;margin:2px 0;border-radius:6px;overflow-wrap:anywhere';

    if (type === 'subagent_start') {
        element.style.cssText += ';border-left:3px solid #a78bfa;background:rgba(99,102,241,0.06);color:#c4b5fd';
        if (subagentId) element.dataset.subagentId = subagentId;
        element.dataset.subagentKind = isBackground ? 'background' : 'agent';
        const header = document.createElement('div');
        header.style.cssText = 'cursor:pointer;user-select:none';
        const noun = isBackground ? 'Background task' : 'Sub-agent';
        header.innerHTML = `<span class="sa-caret">▶</span> ${isBackground ? '⚙️' : '🤖'} <span style="color:#e2e8f0">${noun}: "${DOMPurify.sanitize(description)}"</span>${meta.type ? ` <span style="color:#64748b;font-size:10px">(${DOMPurify.sanitize(meta.type)})</span>` : ''}`;
        // Между `subagent_start` и `subagent_end` НЕТ ни одного события (замер 28.08:
        // 239 задач, только два события на задачу). Поэтому единственный честный признак
        // жизни — часы, которые идут у клиента. Медиана задачи 3.5 с, но p90 = 34 с и
        // максимум 598 с: без тикающего счётчика долгая задача неотличима от повисшей.
        _startSubagentClock(element, ts);
        const body = document.createElement('div');
        body.className = 'sa-body';
        body.style.cssText = 'margin-top:4px;padding-left:14px;border-left:1px dashed #4c1d95;display:none;font-size:10px;color:#94a3b8;white-space:pre-wrap;max-height:300px;overflow-y:auto';
        let expanded = false;
        header.addEventListener('click', () => {
            expanded = !expanded;
            body.style.display = expanded ? 'block' : 'none';
            header.querySelector('.sa-caret').textContent = expanded ? '▼' : '▶';
        });
        element.append(header, body);
    } else if (type === 'subagent_progress') {
        const tokenCount = parseInt(meta.tokens || '0');
        const tokens = meta.tokens ? (tokenCount >= 1000 ? (tokenCount / 1000).toFixed(1) + 'k' : meta.tokens) : '';
        const line = `⏳ ${meta.tool ? 'using ' + meta.tool : 'working'}${tokens ? ' | ' + tokens + ' tokens' : ''}`;
        const host = subagentId ? chat.querySelector(`[data-subagent-id="${CSS.escape(subagentId)}"]`) : null;
        if (host) {
            let progress = host.querySelector('.sa-progress');
            if (!progress) {
                progress = document.createElement('div');
                progress.className = 'sa-progress';
                progress.style.cssText = 'font-size:10px;color:#64748b;padding-left:14px;margin-top:2px';
                host.appendChild(progress);
            }
            progress.textContent = line;
            return true;
        }
        element.style.cssText += ';color:#64748b';
        element.textContent = `⏳ ${isBackground ? 'Background task' : 'Sub-agent'} "${description}" — ${line}`;
    } else {
        const succeeded = !meta.status || ['completed', 'shutdown'].includes(meta.status);
        const host = subagentId ? chat.querySelector(`[data-subagent-id="${CSS.escape(subagentId)}"]`) : null;
        const summary = textParts.slice(1).join(' | ').trim();
        if (host) {
            const header = host.querySelector('div');
            const noun = host.dataset.subagentKind === 'background' ? 'Background task' : 'Sub-agent';
            if (header) header.innerHTML = `<span class="sa-caret">▶</span> ${succeeded ? '✅' : '❌'} <span style="color:#e2e8f0">${noun} ${succeeded ? 'done' : 'failed'}: "${DOMPurify.sanitize(description)}"</span>`;
            host.querySelector('.sa-progress')?.remove();
            _stopSubagentClock(host);
            if (summary) {
                const summaryElement = document.createElement('div');
                summaryElement.style.cssText = 'font-size:10px;color:#94a3b8;margin-top:2px;padding-left:14px;white-space:pre-wrap';
                summaryElement.textContent = summary;
                host.appendChild(summaryElement);
            }
            host.style.borderLeftColor = succeeded ? '#22c55e' : '#ef4444';
            return true;
        }
        element.style.cssText += `;border-left:3px solid ${succeeded ? '#22c55e' : '#ef4444'};background:rgba(${succeeded ? '34,197,94' : '239,68,68'},0.06);color:${succeeded ? '#86efac' : '#fca5a5'}`;
        const noun = isBackground ? 'Background task' : 'Sub-agent';
        element.innerHTML = `${succeeded ? '✅' : '❌'} <span style="color:#e2e8f0">${noun} ${succeeded ? 'completed' : 'failed'}${description ? ': "'+DOMPurify.sanitize(description)+'"' : ''}</span>`;
        if (summary) {
            const summaryElement = document.createElement('div');
            summaryElement.style.cssText = 'font-size:10px;color:#94a3b8;margin-top:2px;padding-left:20px;white-space:pre-wrap';
            summaryElement.textContent = summary.length > 300 ? summary.slice(0, 300) + '…' : summary;
            element.appendChild(summaryElement);
        }
    }

    addTimestamp(element, ts);
    insertAndFollow(element, () => {
        if (type !== 'subagent_start' || !subagentId) return;
        _flushPendingSubagentLogs(subagentId, subagentId);
        _flushPendingSubagentLogs(meta.tool_use_id, subagentId);
    });
    return true;
}

function _renderFullToolCall(content, payload, div) {
    const colonIdx = content.indexOf(':');
    const rawName = canonicalToolName(colonIdx > 0 ? content.slice(0, colonIdx).trim() : content.slice(0, 30));
    const body = colonIdx > 0 ? content.slice(colonIdx + 1).trim() : '';
    const icon = toolIcon(rawName);
    const short = toolShortName(rawName);
    const isOrch = rawName.startsWith('mcp__orchestra__');

    div.dataset.lastTool = '1';
    div.dataset.toolContent = content;
    div.dataset.toolRawName = rawName;
    div.style.cursor = 'pointer';
    if (payload?.tool_use_id) div.dataset.toolUseId = payload.tool_use_id;
    let codexItemId = '';
    try {
        const parsed = JSON.parse(body);
        if (parsed._codex_item_id) {
            codexItemId = parsed._codex_item_id;
            if (!div.dataset.toolUseId) div.dataset.toolUseId = codexItemId;
        }
    } catch {}

    const header = document.createElement('div');
    header.className = 'flex items-center gap-1.5 text-xs font-medium mb-1';
    header.style.color = isOrch ? '#a78bfa' : '#38bdf8';
    let toolDesc = '';
    try { toolDesc = JSON.parse(body).description || ''; } catch {}
    header.innerHTML = `${icon} ${DOMPurify.sanitize(short)}${toolDesc ? ` <span style="color:#64748b;font-weight:normal">— ${DOMPurify.sanitize(toolDesc)}</span>` : ''}`;
    div.appendChild(header);

    // Единственный вызов, которым оркестратор зовёт юзера (#241). Красный и без JSON:
    // юзер ищет эти строки глазами, а `reason` объясняет, зачем дёрнули.
    const isNotify = rawName === NOTIFY_USER_TOOL;
    if (isNotify) {
        let reason = '';
        try { reason = JSON.parse(body).reason || ''; } catch {}
        div.classList.add('chat-notify-user');
        header.textContent = '🔔 Оркестратор зовёт';
        header.style.color = '#fca5a5';
        const reasonEl = document.createElement('div');
        reasonEl.className = 'chat-notify-user-reason';
        reasonEl.textContent = reason || body;
        div.appendChild(reasonEl);
    }
    const isSendMsg = rawName === 'mcp__orchestra__send_message';
    if (isSendMsg) {
        try {
            const d = JSON.parse(body);
            const to = d.to || d.message?.substring(0, 30) || '?';
            const msg = d.message || '';
            header.textContent = `📨 → ${to}`;
            header.style.color = '#a78bfa';
            const SEND_PREVIEW_H = 90;
            const bodyEl = document.createElement('div');
            bodyEl.className = 'text-xs opacity-80 markdown-body';
            bodyEl.style.cssText = `max-height:${SEND_PREVIEW_H}px;overflow-y:hidden;overflow-x:hidden;overflow-wrap:anywhere;word-break:break-word`;
            bodyEl.innerHTML = DOMPurify.sanitize(marked.parse(msg));
            div.appendChild(bodyEl);
            const hint = document.createElement('div');
            hint.className = 'text-xs mt-1';
            hint.style.cssText = 'color:#a78bfa;cursor:pointer';
            hint.textContent = '▼ expand';
            div.appendChild(hint);
            div.style.cursor = 'pointer';
            let sendExpanded = false;
            div.addEventListener('click', (e) => {
                if (e.target.tagName === 'A') return;
                sendExpanded = !sendExpanded;
                bodyEl.style.maxHeight = sendExpanded ? 'none' : SEND_PREVIEW_H + 'px';
                bodyEl.style.overflowY = sendExpanded ? 'visible' : 'hidden';
                hint.textContent = sendExpanded ? '▲ collapse' : '▼ expand';
            });
            requestAnimationFrame(() => {
                if (bodyEl.scrollHeight <= SEND_PREVIEW_H + 4) { hint.style.display = 'none'; bodyEl.style.maxHeight = 'none'; bodyEl.style.overflowY = 'visible'; }
            });
            _appendFullToolArguments(div, rawName, d);
            div.dataset.isEdit = '1';
        } catch {}
    }
    const isSpawnWorker = rawName === 'mcp__orchestra__spawn_worker';
    if (isSpawnWorker) {
        try {
            const d = JSON.parse(body);
            const workerName = d.name || '?';
            const task = d.task || '';
            const model = d.model || 'claude-sonnet-4-6';
            const sysPrompt = d.system_prompt || '';
            const repoPath = d.repo_path || '';

            setCodexToolTitle(header, `Spawning ${workerName}`, '🚀');
            header.style.color = '#a78bfa';
            div.dataset.isSpawnWorker = '1';
            div.dataset.workerName = workerName;

            if (model) {
                const badge = document.createElement('span');
                const color = _modelColor(model);
                badge.textContent = _modelLabel(model);
                badge.style.cssText = `font-size:9px;padding:1px 6px;border-radius:9999px;border:1px solid;color:${color};border-color:${color};opacity:0.8;vertical-align:middle;margin-left:6px`;
                header.appendChild(badge);
            }
            const role = d.role || '';
            if (role && role !== 'worker') {
                const roleBadge = document.createElement('span');
                roleBadge.textContent = role;
                roleBadge.style.cssText = 'font-size:9px;padding:1px 6px;border-radius:9999px;border:1px solid;color:#fbbf24;border-color:#fbbf24;opacity:0.8;vertical-align:middle;margin-left:4px';
                header.appendChild(roleBadge);
            }

            const PREVIEW = 200;
            let cutAt = PREVIEW;
            if (task.length > PREVIEW) {
                const nl = task.lastIndexOf('\n', PREVIEW);
                if (nl > PREVIEW / 2) cutAt = nl;
            }
            const hasMoreTask = task.length > cutAt;
            const expandables = [];

            if (task) {
                const taskEl = document.createElement('div');
                taskEl.className = 'text-xs opacity-80 markdown-body';
                taskEl.innerHTML = DOMPurify.sanitize(marked.parse(hasMoreTask ? task.slice(0, cutAt) : task));
                div.appendChild(taskEl);
                if (hasMoreTask) {
                    const restEl = document.createElement('div');
                    restEl.className = 'text-xs opacity-80 markdown-body';
                    restEl.innerHTML = DOMPurify.sanitize(marked.parse(task.slice(cutAt)));
                    restEl.style.display = 'none';
                    div.appendChild(restEl);
                    expandables.push(restEl);
                }
            }

            if (sysPrompt) {
                const promptLabel = document.createElement('div');
                promptLabel.className = 'text-xs mt-2';
                promptLabel.style.cssText = 'color:#64748b;font-weight:500';
                promptLabel.textContent = '📋 System prompt';
                promptLabel.style.display = 'none';
                div.appendChild(promptLabel);
                expandables.push(promptLabel);
                const promptEl = document.createElement('div');
                promptEl.style.cssText = 'margin-top:4px;padding:6px 8px;background:#0d1117;border:1px solid #1e293b;border-radius:6px;font-size:11px;white-space:pre-wrap;word-break:break-word;color:#94a3b8;max-height:200px;overflow-y:auto;display:none';
                promptEl.textContent = sysPrompt;
                div.appendChild(promptEl);
                expandables.push(promptEl);
            }

            if (repoPath) {
                const pathEl = document.createElement('div');
                pathEl.style.cssText = 'font-size:10px;color:#475569;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
                pathEl.textContent = repoPath;
                pathEl.title = repoPath;
                div.appendChild(pathEl);
            }

            if (expandables.length) {
                const hint = document.createElement('div');
                hint.className = 'text-xs mt-1';
                hint.style.cssText = 'color:#a78bfa;cursor:pointer';
                hint.textContent = `▼ expand`;
                div.appendChild(hint);
                div.style.cursor = 'pointer';
                let spawnExpanded = false;
                div.addEventListener('click', (e) => {
                    if (e.target.tagName === 'A') return;
                    spawnExpanded = !spawnExpanded;
                    expandables.forEach(el => el.style.display = spawnExpanded ? 'block' : 'none');
                    hint.textContent = spawnExpanded ? '▲ collapse' : '▼ expand';
                });
            }

            _appendFullToolArguments(div, rawName, d);

            div.dataset.isEdit = '1';
        } catch {}
    }
    const isRunFan = rawName === 'mcp__orchestra__run_fan';
    if (isRunFan) {
        try {
            const d = JSON.parse(body);
            setCodexToolTitle(header, _runFanSummary(d).replace(/^🎼 /, ''), '🎼');
            header.style.color = '#a78bfa';
            const items = _runFanItems(d);
            if (items.length) {
                const list = document.createElement('div');
                list.className = 'run-fan-items';
                for (const item of items) {
                    const row = document.createElement('div');
                    row.className = 'run-fan-item';
                    const model = item.model ? ` · ${_modelLabel(item.model)}` : '';
                    row.textContent = `${item.name} · ${item.role}${model}`;
                    list.appendChild(row);
                }
                div.appendChild(list);
            }
            _appendFullToolArguments(div, rawName, d);
        } catch {}
    }
    if (isRunFan) div.dataset.isEdit = '1';
    const isWebSearchCall = rawName === 'mcp__websearch__search' || rawName === 'mcp__websearch__search_web' || rawName === 'WebSearch';
    if (isWebSearchCall) {
        try {
            const d = JSON.parse(body);
            setCodexToolTitle(header, 'Web search', '🌐');
            header.style.color = '#38bdf8';
            div.dataset.isCodexWebSearch = '1';
            updateCodexWebSearchActivity(div, codexWebSearchSpec(d));
            if (d.model) {
                const badge = document.createElement('span');
                badge.textContent = d.model;
                badge.style.cssText = 'font-size:9px;padding:1px 6px;border-radius:9999px;border:1px solid #38bdf8;color:#38bdf8;opacity:0.8;vertical-align:middle;margin-left:6px';
                header.appendChild(badge);
            }
        } catch {}
    }
    const isToolSearchCall = rawName === 'ToolSearch';
    if (isToolSearchCall) {
        try {
            const d = JSON.parse(body);
            const q = d.query || '';
            header.textContent = `🔍 Loading: ${q}`;
            header.style.color = '#38bdf8';
        } catch {}
    }
    const isBugReport = rawName === 'mcp__orchestra__report_bug';
    if (isBugReport) {
        try {
            const d = JSON.parse(body);
            header.textContent = `🐛 Bug: ${d.title || '?'}`;
            header.style.color = '#f97316';
            if (d.description) {
                const descLines = d.description.split('\n');
                const PREVIEW = 5;
                const descEl = document.createElement('div');
                descEl.className = 'text-xs markdown-body';
                descEl.style.cssText = 'margin-top:4px;max-height:90px;overflow-y:hidden;overflow-x:hidden;overflow-wrap:anywhere;word-break:break-word;line-height:1.5;color:#cbd5e1';
                descEl.innerHTML = DOMPurify.sanitize(marked.parse(d.description));
                div.appendChild(descEl);
                if (descLines.length > PREVIEW) {
                    const hint = document.createElement('div');
                    hint.className = 'text-xs mt-1';
                    hint.style.cssText = 'color:#f97316;cursor:pointer';
                    hint.textContent = '▼ expand';
                    div.appendChild(hint);
                    let bugExpanded = false;
                    div.style.cursor = 'pointer';
                    div.addEventListener('click', (e) => {
                        if (e.target.tagName === 'A') return;
                        bugExpanded = !bugExpanded;
                        descEl.style.maxHeight = bugExpanded ? 'none' : '90px';
                        descEl.style.overflowY = bugExpanded ? 'visible' : 'hidden';
                        hint.textContent = bugExpanded ? '▲ collapse' : '▼ expand';
                    });
                }
            }
        } catch {}
    }
    const isWebFetch = rawName === 'WebFetch' || rawName === 'mcp__websearch__web_fetch';
    if (isWebFetch) {
        try {
            const d = JSON.parse(body);
            const url = d.url || '';
            let domain = '?';
            try { domain = new URL(url).hostname; } catch {}
            header.textContent = `🌐 Fetching: ${domain}`;
            header.style.color = '#38bdf8';
            if (url) {
                const linkEl = document.createElement('a');
                linkEl.href = url;
                linkEl.target = '_blank';
                linkEl.style.cssText = 'display:block;font-size:10px;color:#64748b;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-decoration:none';
                linkEl.textContent = url;
                linkEl.onmouseenter = () => linkEl.style.color = '#94a3b8';
                linkEl.onmouseleave = () => linkEl.style.color = '#64748b';
                div.appendChild(linkEl);
            }
            if (d.prompt) {
                const promptEl = document.createElement('div');
                promptEl.className = 'text-xs';
                promptEl.style.cssText = 'margin-top:4px;color:#94a3b8;max-height:90px;overflow:hidden;white-space:pre-wrap';
                promptEl.textContent = d.prompt;
                div.appendChild(promptEl);
                if (d.prompt.split('\n').length > 5 || d.prompt.length > 300) {
                    const hint = document.createElement('div');
                    hint.className = 'text-xs mt-1';
                    hint.style.cssText = 'color:#38bdf8;cursor:pointer';
                    hint.textContent = '▼ expand';
                    div.appendChild(hint);
                    let fetchExpanded = false;
                    div.style.cursor = 'pointer';
                    div.addEventListener('click', (e) => {
                        if (e.target.tagName === 'A') return;
                        fetchExpanded = !fetchExpanded;
                        promptEl.style.maxHeight = fetchExpanded ? 'none' : '90px';
                        promptEl.style.overflowY = fetchExpanded ? 'visible' : 'hidden';
                        hint.textContent = fetchExpanded ? '▲ collapse' : '▼ expand';
                    });
                }
            }
        } catch {}
    }
    const isSendFile = rawName === 'mcp__orchestra__send_file';
    if (isSendFile) {
        try {
            const d = JSON.parse(body);
            const filePath = d.path || '';
            const fileName = filePath.split('/').pop() || '?';
            header.textContent = `📎 Sending: ${fileName}`;
            header.style.color = '#22c55e';
            if (filePath) div.dataset.filePath = filePath;
            _appendCaption(div, d.caption);
            if (filePath) {
                const pathEl = document.createElement('div');
                pathEl.style.cssText = 'font-size:10px;color:#475569;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
                pathEl.textContent = filePath;
                pathEl.title = filePath;
                div.appendChild(pathEl);
            }
        } catch {}
    }
    const isSendFiles = rawName === 'mcp__orchestra__send_files';
    if (isSendFiles) {
        try {
            const d = JSON.parse(body);
            const paths = Array.isArray(d.paths) ? d.paths.filter(path => typeof path === 'string' && path) : [];
            div.dataset.filePaths = JSON.stringify(paths);
            header.textContent = `📎 Sending ${paths.length} files`;
            header.style.color = '#22c55e';
            _appendCaption(div, d.caption);
            renderSendFilesToolCard(div, paths);
        } catch {}
    }
    const _orchSimple = {
        'mcp__orchestra__kill_worker': (d) => ({ icon: '💀', label: `Kill: ${d.name||'?'}`, color: '#ef4444' }),
        'mcp__orchestra__stop_worker': (d) => ({ icon: '⏸️', label: `Stop: ${d.name||'?'}`, color: '#eab308' }),
        'mcp__orchestra__compact_worker': (d) => ({ icon: '🗜', label: `Compact: ${d.name||'?'}`, color: '#eab308' }),
        'mcp__orchestra__rename_worker': (d) => ({ icon: '✏️', label: `Rename: ${d.old_name||'?'} → ${d.new_name||'?'}`, color: '#38bdf8' }),
        'mcp__orchestra__change_worker_model': (d) => ({ icon: '🔄', label: `Model: ${d.name||'?'} → ${d.model||'?'}`, color: '#38bdf8' }),
        'mcp__orchestra__update_worker_description': (d) => ({ icon: '✏️', label: `${d.name||'?'} — description updated`, color: '#38bdf8', sub: d.description ? `"${d.description}"` : '' }),
        'mcp__orchestra__merge_worker': (d) => ({ icon: '🔀', label: `Merge: ${d.name||'?'}`, color: '#a78bfa' }),
        'mcp__orchestra__list_agents': () => ({ icon: '🎼', label: 'Agents', color: '#a78bfa' }),
        'mcp__orchestra__list_orchestrators': () => ({ icon: '🎯', label: 'Orchestrators', color: '#a78bfa' }),
        'mcp__orchestra__get_worker_logs': (d) => ({ icon: '📋', label: `Logs: ${d.name||'?'}`, color: '#a78bfa', sub: d.limit ? `${d.limit} entries` : '' }),
        'mcp__orchestra__get_worker_info': (d) => ({ icon: '🤖', label: `Info: ${d.name||'?'}`, color: '#a78bfa' }),
        'mcp__orchestra__task_create': (d) => ({ icon: '📋', label: `создаёт задачу «${typeof d.title === 'string' ? d.title : '?'}»`, color: '#22c55e', sub: d.price ? `${d.price} ${CUR}` : '' }),
        'mcp__orchestra__task_update': (d) => {
            const status = typeof d.status === 'string' && d.status.length > 0 ? ` • статус ${d.status}` : '';
            return { icon: '✏️', label: `обновляет задачу #${taskNum(d.par)||'?'}${status}`, color: '#38bdf8' };
        },
        'mcp__orchestra__task_list': (d) => {
            const _safeTaskFilter = (value) => typeof value === 'string' && value.length <= 32 && !/[<>\"'`]/.test(value);
            const f = [d.status,d.project,d.assignee]
                .map((value) => (typeof value === 'string' ? value.trim() : ''))
                .filter((value) => value && _safeTaskFilter(value))
                .join(', ');
            return { icon: '📋', label: `читает список задач${f ? ` (${f})` : ''}`, color: '#a78bfa' };
        },
        'mcp__orchestra__task_get': (d) => ({ icon: '📋', label: `читает задачу #${taskNum(d.par)||'?'}`, color: '#a78bfa' }),
        'mcp__orchestra__bg_create': (d) => { const i = _JOB_ICONS[d.type]||'⚙️'; return { icon: i, label: `BG ${d.type||'job'}${d.delay_seconds ? ' '+Math.round(d.delay_seconds/60)+'m' : ''}`, color: '#38bdf8', sub: d.message || d.target || '' }; },
        'mcp__orchestra__bg_list': () => ({ icon: '📊', label: 'BG Jobs', color: '#a78bfa' }),
        'mcp__orchestra__bg_cancel': (d) => ({ icon: '⏹', label: `Cancel ${(d.job_id||'').slice(0,8)}`, color: '#94a3b8' }),
    };
    const isOrchSimple = _orchSimple[rawName];
    if (isOrchSimple) {
        try {
            const d = JSON.parse(body);
            const cfg = isOrchSimple(d);
            header.textContent = `${cfg.icon} ${cfg.label}`;
            header.style.color = cfg.color;
            if (cfg.sub) {
                const subEl = document.createElement('div');
                subEl.style.cssText = 'font-size:10px;color:#475569;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis';
                subEl.textContent = cfg.sub;
                div.appendChild(subEl);
            }
        } catch {}
    }
    const isGlob = rawName === 'Glob';
    if (isGlob) {
        try {
            const d = JSON.parse(body);
            header.textContent = `🔎 Glob: ${d.pattern || '?'}`;
            header.style.color = '#38bdf8';
            if (d.path) {
                const pathEl = document.createElement('div');
                pathEl.style.cssText = 'font-size:10px;color:#475569;margin-top:2px';
                pathEl.textContent = d.path;
                div.appendChild(pathEl);
            }
        } catch {}
    }
    const isSkill = rawName === 'Skill';
    if (isSkill) {
        try {
            const d = JSON.parse(body);
            header.textContent = `⚡ Skill: ${d.skill || '?'}`;
            header.style.color = '#eab308';
        } catch {}
    }
    const isBashTool = rawName === 'Bash';
    if (isBashTool) {
        try {
            let cmd = body;
            let commandData = {};
            try {
                commandData = JSON.parse(body);
                cmd = commandData.command || body;
            } catch {}
            cmd = cmd.replace(/^\/(?:usr\/)?bin\/(?:bash|zsh) -lc /, '').replace(/^["']|["']$/g, '');
            const cmdLines = cmd.split('\n');
            const PREVIEW_LINES = 3;
            const previewCmd = cmdLines.slice(0, PREVIEW_LINES).join('\n');
            const restCmd = cmdLines.slice(PREVIEW_LINES).join('\n');
            const hasMoreCmd = cmdLines.length > PREVIEW_LINES;
            const cmdWrap = document.createElement('div');
            cmdWrap.className = 'diff-view';
            cmdWrap.style.marginTop = '4px';
            const previewPre = document.createElement('pre');
            previewPre.style.cssText = 'margin:0;padding:6px 8px;font-size:11px;overflow-x:auto;background:#0d1117;border:none';
            previewPre.textContent = previewCmd;
            cmdWrap.appendChild(previewPre);
            if (hasMoreCmd) {
                const restPre = document.createElement('pre');
                restPre.style.cssText = 'margin:0;padding:0 8px 6px;font-size:11px;overflow-x:auto;background:#0d1117;border:none;display:none';
                restPre.dataset.role = 'bash-rest';
                restPre.textContent = restCmd;
                cmdWrap.appendChild(restPre);
                const hint = document.createElement('div');
                hint.className = 'diff-file';
                hint.dataset.role = 'bash-hint';
                hint.dataset.count = cmdLines.length - PREVIEW_LINES;
                hint.style.cssText = 'cursor:pointer;text-align:center;color:#38bdf8;font-size:10px';
                hint.textContent = `▼ ${cmdLines.length - PREVIEW_LINES} more lines`;
                cmdWrap.appendChild(hint);
            }
            div.appendChild(cmdWrap);
            const actions = commandData.command_actions || [];
            if (actions.length) {
                const actionRow = document.createElement('div');
                actionRow.className = 'codex-command-actions';
                for (const action of actions) {
                    const pill = document.createElement('span');
                    pill.className = `codex-command-action codex-command-${action.type || 'unknown'}`;
                    const actionIcon = action.type === 'read' ? '📖' :
                        action.type === 'search' ? '🔎' :
                        action.type === 'listFiles' ? '🗂' : '⌁';
                    const detail = action.query || action.path || action.name || '';
                    pill.textContent = `${actionIcon} ${action.type || 'command'}${detail ? ': ' + detail : ''}`;
                    pill.title = action.command || '';
                    actionRow.appendChild(pill);
                }
                div.appendChild(actionRow);
            }
            div.dataset.isBash = '1';
            div.style.cursor = 'pointer';
            let bashExpanded = false;
            div.addEventListener('click', (e) => {
                if (e.target.tagName === 'A') return;
                bashExpanded = !bashExpanded;
                const restPre = cmdWrap.querySelector('[data-role="bash-rest"]');
                const hint = cmdWrap.querySelector('[data-role="bash-hint"]');
                if (restPre) restPre.style.display = bashExpanded ? 'block' : 'none';
                if (hint) hint.textContent = bashExpanded ? '▲ collapse' : `▼ ${hint.dataset.count} more lines`;
                const resWrap = div.querySelector('[data-role="bash-result"]');
                const resHint = div.querySelector('[data-role="bash-result-hint"]');
                if (resWrap) resWrap.style.display = bashExpanded ? 'block' : 'none';
                if (resHint) resHint.textContent = bashExpanded ? '▲ collapse result' : `▼ ${resHint.dataset.count} more lines`;
            });
        } catch {}
    }
    const isFileChangeTool = rawName === 'FileChange';
    if (isFileChangeTool) {
        const patch = renderCodexFileChange(body);
        header.textContent = '📝 Applying file changes';
        header.style.color = '#f59e0b';
        if (patch) div.appendChild(patch);
        div.dataset.isFileChange = '1';
    }
    const isViewImageTool = rawName === 'ViewImage';
    if (isViewImageTool) {
        try {
            const data = JSON.parse(body);
            const path = data.file_path || '';
            header.textContent = `🖼 Viewing ${(path.split('/').pop() || 'image')}`;
            const img = document.createElement('img');
            img.src = `/api/files/raw?path=${encodeURIComponent(path)}&t=${Date.now()}`;
            img.loading = 'eager';
            img.className = 'codex-tool-image';
            img.alt = path.split('/').pop() || 'Viewed image';
            img.addEventListener('error', () => {
                img.classList.add('codex-tool-image-error');
                img.alt = 'Image unavailable';
            });
            img.addEventListener('load', () => {
                img.classList.remove('codex-tool-image-error');
            });
            img.addEventListener('click', () => openImageLightbox(img.src));
            div.appendChild(img);
        } catch {}
    }
    const isImageGenerationTool = rawName === 'ImageGeneration';
    if (isImageGenerationTool) {
        header.textContent = '🎨 Generating image';
        header.style.color = '#f472b6';
    }
    const isSleepTool = rawName === 'Sleep';
    if (isSleepTool) {
        try {
            const data = JSON.parse(body);
            header.textContent = `⏱ Waiting ${((data.duration_ms || 0) / 1000).toFixed(1)}s`;
            header.style.color = '#94a3b8';
        } catch {}
    }
    const isTodoWrite = rawName === 'TodoWrite';
    if (isTodoWrite) {
        try {
            const d = JSON.parse(body);
            const todos = Array.isArray(d.todos) ? d.todos : [];
            const done = todos.filter(t => t.status === 'completed').length;
            header.textContent = `📝 Todos ${done}/${todos.length}`;
            header.style.color = '#38bdf8';
            const listEl = document.createElement('div');
            listEl.className = 'text-xs mt-1';
            listEl.style.cssText = 'display:flex;flex-direction:column;gap:2px';
            const _todoMark = (st) => st === 'completed' ? ['✅', '#4ade80', 'line-through']
                : st === 'in_progress' ? ['◔', '#fbbf24', 'none'] : ['☐', '#64748b', 'none'];
            for (const t of todos) {
                const [mark, color, deco] = _todoMark(t.status);
                const row = document.createElement('div');
                row.style.cssText = 'display:flex;gap:6px;align-items:baseline;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
                const m = document.createElement('span');
                m.textContent = mark;
                m.style.minWidth = '1.2em';
                const c = document.createElement('span');
                c.textContent = t.content || '';
                c.style.cssText = `color:${color};text-decoration:${deco}`;
                row.append(m, c);
                listEl.appendChild(row);
            }
            if (todos.length) div.appendChild(listEl);
            div.dataset.isEdit = '1';   // swallow the raw JSON result
        } catch {}
    }
    const isReviewTool = rawName === 'Review';
    if (isReviewTool) {
        try {
            const d = JSON.parse(body);
            const focus = String(d.focus || '').trim();
            header.textContent = `🧠 Review${focus ? ': ' + focus.slice(0, 100) : ''}`;
            header.title = focus;
            header.style.color = '#a78bfa';
        } catch {}
    }
    const isAgentTool = rawName === 'Agent';
    if (isAgentTool) {
        try {
            const d = JSON.parse(body);
            const desc = d.description || '';
            const prompt = d.prompt || '';
            header.textContent = '🤖 Agent';
            header.style.color = '#a78bfa';
            if (desc) {
                const descEl = document.createElement('div');
                descEl.className = 'text-xs font-medium mb-1';
                descEl.style.color = '#c7d2fe';
                descEl.textContent = desc;
                div.appendChild(descEl);
            }
            if (prompt) {
                const promptLines = prompt.split('\n');
                const PREVIEW_LINES = 2;
                const previewPrompt = promptLines.slice(0, PREVIEW_LINES).join('\n');
                const restPrompt = promptLines.slice(PREVIEW_LINES).join('\n');
                const hasMorePrompt = promptLines.length > PREVIEW_LINES;
                const promptWrap = document.createElement('div');
                promptWrap.className = 'diff-view';
                promptWrap.style.marginTop = '4px';
                const previewPre = document.createElement('pre');
                previewPre.style.cssText = 'margin:0;padding:6px 8px;font-size:11px;overflow-x:auto;background:#0d1117;border:none;white-space:pre-wrap;word-break:break-word';
                previewPre.textContent = previewPrompt;
                promptWrap.appendChild(previewPre);
                if (hasMorePrompt) {
                    const restPre = document.createElement('pre');
                    restPre.style.cssText = 'margin:0;padding:0 8px 6px;font-size:11px;overflow-x:auto;background:#0d1117;border:none;white-space:pre-wrap;word-break:break-word;display:none';
                    restPre.dataset.role = 'agent-rest';
                    restPre.textContent = restPrompt;
                    promptWrap.appendChild(restPre);
                    const hint = document.createElement('div');
                    hint.className = 'diff-file';
                    hint.dataset.role = 'agent-hint';
                    hint.dataset.count = promptLines.length - PREVIEW_LINES;
                    hint.style.cssText = 'cursor:pointer;text-align:center;color:#a78bfa;font-size:10px';
                    hint.textContent = `▼ ${promptLines.length - PREVIEW_LINES} more lines`;
                    promptWrap.appendChild(hint);
                }
                div.appendChild(promptWrap);
                div.style.cursor = 'pointer';
                let agentExpanded = false;
                div.addEventListener('click', (e) => {
                    if (e.target.tagName === 'A') return;
                    agentExpanded = !agentExpanded;
                    const restPre = promptWrap.querySelector('[data-role="agent-rest"]');
                    const hint = promptWrap.querySelector('[data-role="agent-hint"]');
                    if (restPre) restPre.style.display = agentExpanded ? 'block' : 'none';
                    if (hint) hint.textContent = agentExpanded ? '▲ collapse' : `▼ ${hint.dataset.count} more lines`;
                });
            }
            div.dataset.isEdit = '1';
        } catch {}
    }
    const isGrepTool = rawName === 'Grep';
    if (isGrepTool) {
        try {
            const d = JSON.parse(body);
            const grepPath = d.path || d.glob || '';
            const shortGrepPath = grepPath.replace(/^.*\/worktrees\/[^/]+\/[^/]+\//, '') || grepPath;
            header.textContent = `🔎 Grep: ${d.pattern || ''}${shortGrepPath ? ' in ' + shortGrepPath : ''}`;
            header.style.color = '#38bdf8';
            div.dataset.isGrep = '1';
            div.dataset.grepPattern = d.pattern || '';
            div.dataset.grepPath = grepPath;
        } catch {}
    }
    const isEditTool = rawName === 'Edit' || rawName === 'MultiEdit' || rawName === 'Write';
    const isReadTool = rawName === 'Read';
    if (isReadTool) {
        try { const d = JSON.parse(body); if (d.file_path) div.dataset.filePath = d.file_path; } catch {}
    }
    const diffEl = isEditTool ? renderEditDiff(body) : null;
    const readEl = isReadTool ? renderReadView(body) : null;

    if (readEl) {
        div.appendChild(readEl);
        div.dataset.isRead = '1';
        div.style.cursor = 'pointer';
        div.addEventListener('click', () => {
            const restEl = readEl.querySelector('[data-role="read-rest"]');
            const moreEl = readEl.querySelector('[data-role="read-more"]');
            if (restEl && moreEl) {
                const showing = restEl.style.display !== 'none';
                restEl.style.display = showing ? 'none' : 'block';
                moreEl.textContent = showing ? `▼ ${moreEl.dataset.count} more lines` : `▲ collapse`;
            }
        });
    } else if (diffEl) {
        div.appendChild(diffEl);
        div.dataset.isEdit = '1';
        div.style.cursor = 'pointer';
        div.addEventListener('click', () => {
            const restEl = diffEl.querySelector('[style*="display"]');
            const moreEl = diffEl.querySelector('.diff-file[style*="cursor"]');
            if (restEl && moreEl) {
                const showing = restEl.style.display !== 'none';
                restEl.style.display = showing ? 'none' : 'block';
                const restCount = moreEl.dataset.count || '0';
                moreEl.textContent = showing ? `▼ ${restCount} more lines` : `▲ collapse`;
            }
        });
    } else if (!isSendMsg && !isNotify && !isGrepTool && !isBashTool &&
               !isAgentTool && !isSpawnWorker && !isRunFan && !isWebSearchCall &&
               !isToolSearchCall && !isBugReport && !isWebFetch &&
               !isSendFile && !isSendFiles && !isOrchSimple && !isGlob && !isSkill &&
               !isFileChangeTool && !isViewImageTool &&
               !isImageGenerationTool && !isSleepTool && !isTodoWrite && !isReviewTool) {
        let _inputJsonRendered = false;
        if (body) {
            try {
                const _inputParsed = JSON.parse(body);
                if (_inputParsed && typeof _inputParsed === 'object' && !Array.isArray(_inputParsed)) {
                    const gridWrap = document.createElement('div');
                    gridWrap.className = 'text-xs opacity-80 tool-body';
                    gridWrap.style.cssText = 'margin-top:2px';
                    _renderJsonGrid(_inputParsed, gridWrap);
                    div.appendChild(gridWrap);
                    _inputJsonRendered = true;
                }
            } catch {}
        }
        if (!_inputJsonRendered && body) {
            const toolPreview = body.length > 200 ? body.slice(0, 200) + '…' : body;
            const toolFull = body.length > 200 ? body : null;
            const bodyEl = document.createElement('div');
            bodyEl.style.whiteSpace = 'pre-wrap';
            bodyEl.className = 'text-xs opacity-70 tool-body';
            bodyEl.textContent = toolPreview;
            bodyEl.dataset.preview = toolPreview;
            if (toolFull) bodyEl.dataset.full = toolFull;
            div.appendChild(bodyEl);
            if (toolFull) {
                const remaining = body.split('\n').length - toolPreview.split('\n').length;
                const hint = document.createElement('div');
                hint.className = 'text-xs mt-1';
                hint.style.color = '#38bdf8';
                hint.textContent = `▼ ${remaining} more lines`;
                hint.dataset.role = 'expand-hint';
                div.appendChild(hint);
            }
            let expanded = false;
            div.addEventListener('click', (e) => {
                if (e.target.tagName === 'A') return;
                expanded = !expanded;
                const tb = div.querySelector('.tool-body');
                if (tb && tb.dataset.full) tb.textContent = expanded ? tb.dataset.full : tb.dataset.preview;
                const hint = div.querySelector('[data-role="expand-hint"]');
                if (hint) hint.style.display = expanded ? 'none' : 'block';
                const rb = div.querySelector('.result-body');
                if (rb && rb.dataset.full) rb.innerHTML = '📎 ' + DOMPurify.sanitize(expanded ? rb.dataset.full : rb.dataset.preview, {ADD_ATTR: ['target']});
            });
        }
    }
    if (codexItemId) {
        decorateCodexToolCard(div, div.querySelector('.flex.items-center'), isOrch ? 'orchestra' : 'native');
        _flushCodexToolUpdates(div, codexItemId);
    }
}

function _renderFullToolResult(content, ts, payload, anchor, div, _insertAndFollow, isBase64Image) {
    const chat = $('#chat');
    const resultToolId = payload?.tool_use_id || '';
    const lastTool = _toolForResult(chat, payload, anchor, false);
    if (!lastTool) {
        div.dataset.unmatchedToolResult = '1';
        if (resultToolId) {
            div.dataset.orphanResultFor = resultToolId;
            div._orphanResult = {content, ts, payload};
        }
        const warning = document.createElement('div');
        warning.className = 'text-amber-400 text-xs font-medium mb-1';
        warning.textContent = `⚠️ Результат без вызова${resultToolId ? ` · ${resultToolId}` : ''}`;
        div.appendChild(warning);
    }
    if (lastTool) {
        const liveOutput = lastTool.querySelector('.codex-live-output');
        if (liveOutput) liveOutput.remove();
        completeCodexToolCard(lastTool);
        if (lastTool.dataset.isFileChange) {
            let data = {};
            try { data = JSON.parse(content); } catch {}
            const header = lastTool.querySelector('.flex.items-center');
            const ok = !data.status || data.status === 'completed';
            if (header) {
                header.textContent = `${ok ? '✅' : '❌'} File changes ${ok ? 'applied' : 'failed'}${data.files != null ? ` · ${data.files} file${data.files === 1 ? '' : 's'}` : ''}`;
                header.style.color = ok ? '#4ade80' : '#f87171';
            }
            delete lastTool.dataset.lastTool;
            addTimestamp(lastTool, ts);
            return;
        }
        if (lastTool.dataset.toolRawName === 'ImageGeneration') {
            let data = {};
            try { data = JSON.parse(content); } catch {}
            delete lastTool.dataset.lastTool;
            addTimestamp(lastTool, ts);
            if (payload?.trunc && payload?.id) {
                void _restoreImageGenerationResult(lastTool, payload);
                return;
            }
            _completeImageGenerationTool(lastTool, data);
            return;
        }
        if (lastTool.dataset.toolRawName === 'ViewImage') {
            const header = lastTool.querySelector('.flex.items-center');
            if (header) header.style.color = '#7dd3fc';
            const img = lastTool.querySelector('.codex-tool-image');
            if (img && (!img.complete || !img.naturalWidth)) {
                img.src = img.src.replace(/([?&])t=\d+/, `$1t=${Date.now()}`);
            }
            delete lastTool.dataset.lastTool;
            addTimestamp(lastTool, ts);
            return;
        }
        if (lastTool.dataset.toolRawName === 'Sleep') {
            const header = lastTool.querySelector('.flex.items-center');
            if (header) {
                header.textContent = '✓ Wait completed';
                header.style.color = '#64748b';
            }
            delete lastTool.dataset.lastTool;
            addTimestamp(lastTool, ts);
            return;
        }
    }
    if (isBase64Image) {
        const inlineSrc = _toolResultImageSrc(content);
        if (lastTool) {
            delete lastTool.dataset.lastTool;
            const skeleton = lastTool.querySelector('[data-role="read-skeleton"]');
            if (skeleton) skeleton.remove();
        }
        const target = lastTool || div;
        const origPath = lastTool && lastTool.dataset.filePath;
        if (inlineSrc || origPath || payload?.id) {
            const img = document.createElement('img');
            img.style.cssText = 'max-width:100%;max-height:300px;border-radius:6px;margin-top:6px;cursor:pointer';
            img.style.display = 'none';
            img.addEventListener('click', () => _showImageOverlay(img.src));
            target.appendChild(img);
            // Use original file via API if Read tool has file_path — SDK compresses base64
            _loadToolResultImage(img, origPath, inlineSrc, payload).then(ok => {
                if (ok) img.style.display = '';
                else img.replaceWith(Object.assign(document.createElement('div'), {textContent: '🖼 Image unavailable'}));
            });
        } else {
            const placeholder = document.createElement('div');
            placeholder.className = 'text-xs';
            placeholder.style.cssText = 'color:#64748b;margin-top:4px';
            placeholder.textContent = '🖼 [Image result]';
            target.appendChild(placeholder);
        }
        addTimestamp(target, ts);
        if (!lastTool) {
            _insertAndFollow(div);
        }
        return;
    }
    const toolErrorMatch = content.match(/<tool_use_error>([\s\S]*?)<\/tool_use_error>/);
    if (toolErrorMatch) {
        const errMsg = toolErrorMatch[1].trim();
        const errDiv = document.createElement('div');
        errDiv.className = 'px-3 py-2 rounded-lg text-xs text-red-400 bg-red-950/30 border border-red-900/50';
        errDiv.textContent = '⚠️ ' + errMsg;
        if (lastTool) {
            if (lastTool.dataset.toolRawName === 'mcp__orchestra__send_files') {
                const hdr = lastTool.querySelector('.flex.items-center');
                if (hdr) {
                    hdr.textContent = `❌ Send failed · 0 files accepted`;
                    hdr.style.color = '#ef4444';
                }
            } else if (lastTool.dataset.toolRawName === 'mcp__orchestra__send_file') {
                const hdr = lastTool.querySelector('.flex.items-center');
                if (hdr) {
                    hdr.textContent = '❌ Send failed';
                    hdr.style.color = '#ef4444';
                }
            }
            completeCodexToolCard(lastTool, false);
            delete lastTool.dataset.lastTool;
            const skeleton = lastTool.querySelector('[data-role="read-skeleton"]');
            if (skeleton) skeleton.remove();
            lastTool.appendChild(errDiv);
            addTimestamp(lastTool, ts);
        } else {
            div.appendChild(errDiv);
            addTimestamp(div, ts);
            _insertAndFollow(div);
        }
        return;
    }
    const clean = content.replace(/^\{?"?result"?:\s*"?|"?\}?$/g, '').replace(/\\n/g, '\n');
    // Strip raw JSON link arrays from WebSearch results (shown as ugly JSON at top)
    const stripped = clean.replace(/^(Links:\s*\[.*?\}\]\s*\n?)+/gms, '');
    const escaped = _escHtml(stripped);
    // Render markdown links [text](url) first, then bare URLs
    const mdLinked = escaped.replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" class="text-indigo-400 hover:text-indigo-300 underline">$1</a>');
    const linked = mdLinked.replace(/((?<!href="|">)https?:\/\/[^\s\])"&<]+)/g, '<a href="$1" target="_blank" class="text-indigo-400 hover:text-indigo-300 underline">$1</a>');
    const _resultLines = linked.split('\n');
    const _RESULT_PREVIEW = 5;
    const _hasMore = _resultLines.length > _RESULT_PREVIEW;
    const preview = _hasMore ? _resultLines.slice(0, _RESULT_PREVIEW).join('\n') : linked;
    const full = _hasMore ? linked : null;

    if (lastTool) {
        if (lastTool.dataset.isCodexWebSearch) {
            // Codex шлёт результатом ту же структуру с action/queries — ею обновляем шапку.
            // Встроенный WebSearch и MCP-поиск отдают ТЕКСТ: spec=null, и его надо
            // отрисовать обычным телом результата, а не проглотить ранним return.
            const resultSpec = codexWebSearchSpec(content);
            if (resultSpec) {
                updateCodexWebSearchActivity(lastTool, resultSpec);
                delete lastTool.dataset.lastTool;
                addTimestamp(lastTool, ts);
                return;
            }
        }
        if (lastTool.dataset.isSpawnWorker) {
            const hdr = lastTool.querySelector('.flex.items-center');
            if (hdr) setCodexToolTitle(hdr, `${lastTool.dataset.workerName || 'Worker'} spawned`);
            delete lastTool.dataset.lastTool;
            addTimestamp(lastTool, ts);
            return;
        }
        delete lastTool.dataset.lastTool;
        if (lastTool.dataset.isEdit) {
            addTimestamp(lastTool, ts);
            return;
        }
        const isToolSearch = lastTool.dataset.toolRawName === 'ToolSearch';
        if (isToolSearch) {
            let toolName = '';
            try { const d = JSON.parse(content); toolName = d.tool_name || ''; } catch {}
            if (!toolName) { const m = content.match(/tool_name['":\s]+(\w+)/); toolName = m ? m[1] : ''; }
            const hdr = lastTool.querySelector('.flex.items-center');
            if (hdr && toolName) hdr.textContent = `✅ Loaded: ${toolName}`;
            else if (hdr) hdr.textContent = '✅ Tool loaded';
            addTimestamp(lastTool, ts);
            return;
        }
        if (lastTool.dataset.toolRawName === 'mcp__orchestra__report_bug') {
            const hdr = lastTool.querySelector('.flex.items-center');
            if (hdr) { hdr.textContent = '✅ Bug reported'; hdr.style.color = '#22c55e'; }
            addTimestamp(lastTool, ts);
            return;
        }
        if (lastTool.dataset.toolRawName === 'mcp__orchestra__send_file') {
            const hdr = lastTool.querySelector('.flex.items-center');
            const hasError = content.includes('error') || content.includes('Error') || content.includes('failed');
            if (hdr) {
                hdr.textContent = hasError ? '❌ Send failed' : '✅ Sent to TG';
                hdr.style.color = hasError ? '#ef4444' : '#22c55e';
            }
            const fp = lastTool.dataset.filePath;
            if (!hasError && fp) {
                // Image thumbnail above the buttons — click opens full-size lightbox
                if (/\.(png|jpe?g|gif|webp|svg)$/i.test(fp) && !lastTool.querySelector('.sf-thumb')) {
                    const rawUrl = `/api/files/raw?path=${encodeURIComponent(fp)}&t=${Date.now()}`;
                    const previewUrl = `/api/files/raw?path=${encodeURIComponent(fp)}&preview=640&t=${Date.now()}`;
                    const img = document.createElement('img');
                    img.className = 'sf-thumb';
                    img.src = previewUrl;
                    img.loading = 'lazy';
                    img.decoding = 'async';
                    img.style.cssText = 'display:block;margin-top:6px;max-height:200px;max-width:100%;border-radius:8px;cursor:pointer;border:1px solid rgba(99,102,241,0.2)';
                    img.addEventListener('click', () => openImageLightbox(rawUrl));
                    img.onerror = () => img.remove();  // broken/missing file → no ugly broken-icon
                    lastTool.appendChild(img);
                }
                const btnRow = document.createElement('div');
                btnRow.style.cssText = 'margin-top:4px;display:flex;gap:6px;flex-wrap:wrap';
                const _fileBtn = (label, onClick) => {
                    const b = document.createElement('button');
                    b.textContent = label;
                    b.style.cssText = 'padding:3px 10px;font-size:11px;border-radius:6px;border:1px solid rgba(99,102,241,0.3);background:rgba(15,23,42,0.95);color:#a5b4fc;cursor:pointer;transition:all 0.15s;backdrop-filter:blur(8px)';
                    b.onmouseenter = () => { b.style.borderColor = 'rgba(99,102,241,0.6)'; b.style.color = '#c7d2fe'; };
                    b.onmouseleave = () => { b.style.borderColor = 'rgba(99,102,241,0.3)'; b.style.color = '#a5b4fc'; };
                    b.onclick = onClick;
                    return b;
                };
                btnRow.appendChild(_fileBtn('📥 Download', () => {
                    window.open(`/api/files/raw?path=${encodeURIComponent(fp)}&download=1`, '_blank');
                }));
                if (/\.html?$/i.test(fp)) {
                    btnRow.appendChild(_fileBtn('👁 Preview', () => {
                        window.open(`/api/files/raw?path=${encodeURIComponent(fp)}`, '_blank');
                    }));
                }
                lastTool.appendChild(btnRow);
            }
            addTimestamp(lastTool, ts);
            return;
        }
        if (lastTool.dataset.toolRawName === 'mcp__orchestra__send_files') {
            const paths = _sendFilePaths(lastTool);
            const info = _sendFilesResultInfo(content, paths.length);
            const hdr = lastTool.querySelector('.flex.items-center');
            if (hdr) {
                hdr.textContent = info.hasError
                    ? `❌ Send failed · ${info.count} files accepted`
                    : `✅ Sent to TG · ${info.count} files accepted`;
                hdr.style.color = info.hasError ? '#ef4444' : '#22c55e';
            }
            if (!info.hasError && paths.length) {
                lastTool.querySelectorAll('.sf-file-list, .sf-actions').forEach(el => el.remove());
                renderSendFilesToolCard(lastTool, paths, {downloads: true});
            }
            addTimestamp(lastTool, ts);
            return;
        }
        const _tmTools = ['mcp__orchestra__task_create','mcp__orchestra__task_update','mcp__orchestra__task_list','mcp__orchestra__task_get','mcp__orchestra__bg_list','mcp__orchestra__get_worker_info'];
        if (_tmTools.includes(lastTool.dataset.toolRawName)) {
            const hdr = lastTool.querySelector('.flex.items-center');
            let parsed = null;
            try { parsed = JSON.parse(content); } catch {}
            const tn = lastTool.dataset.toolRawName;
            if (!parsed || parsed.error) {
                if (hdr) { hdr.textContent = `❌ ${parsed?.error || clean.slice(0, 80)}`; hdr.style.color = '#ef4444'; }
                addTimestamp(lastTool, ts);
                return;
            }
            if (tn === 'mcp__orchestra__task_create' || tn === 'mcp__orchestra__task_get') {
                const taskNumber = taskNum(parsed.par ?? parsed.task_id ?? parsed.id) || '?';
                if (hdr) {
                    if (tn.includes('create')) {
                        hdr.textContent = `✅ создаёт задачу «${parsed.title || '?'}»`;
                    } else {
                        hdr.textContent = `📋 читает задачу #${taskNumber}`;
                    }
                    hdr.style.color = tn.includes('create') ? '#22c55e' : '#a78bfa';
                }
                const taskBody = document.createElement('div');
                taskBody.style.marginTop = '4px';
                taskBody.innerHTML = _taskCardBodyHtml(parsed);
                lastTool.appendChild(taskBody);
                const sys = [];
                if (parsed.yougile_id || parsed.yougile_task_id) sys.push(`yougile: ${parsed.yougile_id || parsed.yougile_task_id}`);
                if (parsed.sync_revision) sys.push(`rev: ${parsed.sync_revision}`);
                if (sys.length > 0) {
                    const sEl = document.createElement('div');
                    sEl.style.cssText = 'margin-top:4px;font-size:9px;color:#475569;font-family:monospace';
                    sEl.textContent = sys.join(' · ');
                    lastTool.appendChild(sEl);
                }
            } else if (tn === 'mcp__orchestra__task_update') {
                const _kr = (v) => typeof v === 'number' ? String(Math.abs(v)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ') : v;
                const changes = [];
                if (parsed.old_status && parsed.new_status && parsed.old_status !== parsed.new_status) changes.push(`status ${parsed.old_status}→${parsed.new_status}`);
                if (parsed.updated) {
                    for (const f of parsed.updated) {
                        if (f === 'status') continue;
                        if (f === 'price' && parsed.price_rub != null) changes.push(`price ${_kr(parsed.price_rub)} ${CUR}`);
                        else if (f === 'assignee' && parsed.assignee != null) changes.push(`assignee→${parsed.assignee || '—'}`);
                        else if (f === 'title') changes.push('title');
                        else if (f === 'description') changes.push('description');
                        else changes.push(f);
                    }
                }
                const parNum = (parsed.par || '?').replace(/^[A-Z]+-/, '');
                const titleStr = parsed.title ? ` "${parsed.title.slice(0,40)}"` : '';
                const status = parsed.new_status || parsed.status;
                const statusLabel = typeof status === 'string' && status ? ` • статус ${status}` : '';
                if (hdr) {
                    hdr.textContent = `✏️ обновляет задачу #${parNum}${titleStr}${statusLabel}`;
                    hdr.style.color = '#22c55e';
                }
                if (parsed.old_title && parsed.title && parsed.old_title !== parsed.title) {
                    const titleDiff = document.createElement('div');
                    titleDiff.style.cssText = 'margin-top:3px;font-size:10px';
                    titleDiff.innerHTML = `<span style="color:#64748b;text-decoration:line-through">${DOMPurify.sanitize(parsed.old_title.slice(0,60))}</span> → <span style="color:#e2e8f0">${DOMPurify.sanitize(parsed.title.slice(0,60))}</span>`;
                    lastTool.appendChild(titleDiff);
                }
                if (parsed.description && (parsed.updated || []).includes('description')) {
                    const descWrap = document.createElement('div');
                    descWrap.style.cssText = 'margin-top:4px';
                    if (parsed.old_description) {
                        const oldEl = document.createElement('div');
                        oldEl.style.cssText = 'font-size:10px;color:#64748b;text-decoration:line-through;max-height:40px;overflow:hidden;white-space:pre-wrap;overflow-wrap:anywhere';
                        oldEl.textContent = parsed.old_description.split('\n').slice(0,3).join('\n');
                        descWrap.appendChild(oldEl);
                    }
                    const newEl = document.createElement('div');
                    newEl.style.cssText = 'font-size:10px;color:#86efac;max-height:40px;overflow-y:hidden;overflow-x:hidden;white-space:pre-wrap;overflow-wrap:anywhere;margin-top:2px';
                    newEl.textContent = parsed.description.split('\n').slice(0,3).join('\n') + (parsed.description.split('\n').length > 3 ? '…' : '');
                    descWrap.appendChild(newEl);
                    lastTool.appendChild(descWrap);
                    if (parsed.description.split('\n').length > 3) {
                        lastTool.style.cursor = 'pointer';
                        let _duExp = false;
                        lastTool.addEventListener('click', (e) => {
                            if (e.target.tagName === 'A') return;
                            _duExp = !_duExp;
                            newEl.textContent = _duExp ? parsed.description : parsed.description.split('\n').slice(0,3).join('\n') + '…';
                            newEl.style.maxHeight = _duExp ? 'none' : '40px';
                            newEl.style.overflowY = _duExp ? 'visible' : 'hidden';
                        });
                    }
                }
                const detail = document.createElement('div');
                detail.style.cssText = 'margin-top:3px;font-size:10px;color:#64748b;display:flex;gap:8px;flex-wrap:wrap';
                if (parsed.price_rub > 0) detail.innerHTML += `<span>Price: <b style="color:#eab308">${_kr(parsed.price_rub)} ${CUR}</b></span>`;
                if (detail.innerHTML) lastTool.appendChild(detail);
            } else if (tn === 'mcp__orchestra__task_list') {
                const tasks = parsed.tasks || [];
                const resultMeta = document.createElement('div');
                resultMeta.className = 'text-xs mt-1';
                resultMeta.style.color = '#64748b';
                resultMeta.textContent = `Результат: ${tasks.length}`;
                lastTool.appendChild(resultMeta);
                if (tasks.length > 0 && parsed.detailed) {
                    const container = document.createElement('div');
                    container.style.cssText = 'margin-top:6px;display:flex;flex-direction:column;gap:6px';
                    const PREVIEW = 3;
                    for (const [i, t] of tasks.entries()) {
                        const card = document.createElement('div');
                        card.style.cssText = `padding:6px 8px;border-radius:6px;background:rgba(30,41,59,0.4);border-left:3px solid ${t.status==='done'||t.status==='paid'?'#22c55e':t.status==='in_progress'?'#38bdf8':'#334155'}${i >= PREVIEW ? ';display:none' : ''}`;
                        card.dataset.taskRow = '1';
                        let h = `<div style="font-size:11px;color:#e2e8f0;font-weight:600">${DOMPurify.sanitize(t.par)}: ${DOMPurify.sanitize(t.title)}</div>`;
                        h += _taskCardBodyHtml(t);
                        card.innerHTML = h;
                        container.appendChild(card);
                    }
                    _attachTaskRows(lastTool, container, tasks.length, PREVIEW, 'block');
                } else if (tasks.length > 0) {
                    const container = document.createElement('div');
                    container.style.cssText = 'margin-top:4px;display:flex;flex-direction:column;gap:2px';
                    const PREVIEW = 4;
                    for (const [i, t] of tasks.entries()) {
                        const row = document.createElement('div');
                        row.style.cssText = `font-size:10px;padding:2px 6px;border-radius:4px;background:rgba(30,41,59,0.4);color:#cbd5e1;display:flex;gap:6px;align-items:center${i >= PREVIEW ? ';display:none' : ''}`;
                        row.dataset.taskRow = '1';
                        const priceStr = t.price && t.price !== '0' ? `<span style="color:#eab308">${t.price}</span>` : '';
                        row.innerHTML = `<span style="color:#64748b;font-family:monospace;min-width:32px">#${t.par}</span><span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${DOMPurify.sanitize(t.title)}</span><span style="color:#64748b">${t.status}</span>${priceStr}`;
                        container.appendChild(row);
                    }
                    _attachTaskRows(lastTool, container, tasks.length, PREVIEW, 'flex');
                }
            } else if (tn === 'mcp__orchestra__bg_list') {
                const jobs = Array.isArray(parsed) ? parsed : (parsed.jobs || []);
                if (hdr) hdr.textContent = `📊 ${jobs.length} jobs`;
                if (jobs.length > 0) {
                    const container = document.createElement('div');
                    container.style.cssText = 'margin-top:4px;display:flex;flex-direction:column;gap:2px';
                    for (const j of jobs.slice(0, 8)) {
                        const icon = _JOB_ICONS[j.type] || '⚙️';
                        const st = _JOB_STATUS[j.status] || '⚪';
                        const row = document.createElement('div');
                        row.style.cssText = 'font-size:10px;padding:2px 6px;border-radius:4px;background:rgba(30,41,59,0.4);color:#cbd5e1;display:flex;gap:4px;align-items:center';
                        row.innerHTML = `<span>${icon}</span><span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${DOMPurify.sanitize(j.target_name || '')} ${DOMPurify.sanitize((j.message||'').slice(0,30))}</span><span>${st}</span>`;
                        container.appendChild(row);
                    }
                    lastTool.appendChild(container);
                }
            } else if (tn === 'mcp__orchestra__get_worker_info') {
                const stColor = _STATUS_COLOR[parsed.status] || '#94a3b8';
                const modelShort = _modelLabel(parsed.model);
                if (hdr) {
                    hdr.innerHTML = `🤖 <b>${DOMPurify.sanitize(parsed.name || '?')}</b> <span style="font-size:10px;color:#64748b">(${DOMPurify.sanitize(modelShort)})</span> — <span style="color:${stColor}">${parsed.status || '?'}</span>`;
                }
                const grid = document.createElement('div');
                grid.style.cssText = 'margin-top:4px;display:grid;grid-template-columns:auto 1fr;gap:1px 10px;font-size:10px';
                const _row = (label, val, color) => { if (val != null && val !== '') grid.innerHTML += `<span style="color:#64748b">${label}</span><span style="color:${color||'#cbd5e1'}">${DOMPurify.sanitize(String(val))}</span>`; };
                _row('Role', parsed.is_orchestrator ? '🎯 orchestrator' : '⚙️ worker');
                _row('Branch', parsed.branch, '#818cf8');
                const ctxPct = parsed.context_pct || 0;
                const ctxColor = ctxPct >= 80 ? '#ef4444' : ctxPct >= 50 ? '#eab308' : '#22c55e';
                _row('Context', `${ctxPct}%`, ctxColor);
                _row('Cost', `${MODEL_COST_CURRENCY}${parsed.cost_usd ?? 0}`, '#22c55e');
                if (parsed.task_id) _row('Task', `#${parsed.task_id}`, '#a78bfa');
                if (parsed.total_turns) _row('Turns', parsed.total_turns);
                if (parsed.total_tool_calls) _row('Tool calls', parsed.total_tool_calls);
                if (parsed.total_input_tokens || parsed.total_output_tokens) _row('Tokens', `${(parsed.total_input_tokens||0).toLocaleString()} in / ${(parsed.total_output_tokens||0).toLocaleString()} out`);
                lastTool.appendChild(grid);
                if (parsed.description) {
                    const descEl = document.createElement('div');
                    descEl.style.cssText = 'margin-top:4px;font-size:10px;color:#94a3b8;font-style:italic;max-height:40px;overflow-y:hidden;overflow-x:hidden;overflow-wrap:anywhere';
                    descEl.textContent = parsed.description;
                    lastTool.appendChild(descEl);
                    if (parsed.description.length > 120) {
                        lastTool.style.cursor = 'pointer';
                        let _wiExp = false;
                        lastTool.addEventListener('click', (e) => {
                            if (e.target.tagName === 'A') return;
                            _wiExp = !_wiExp;
                            descEl.style.maxHeight = _wiExp ? 'none' : '40px';
                            descEl.style.overflowY = _wiExp ? 'visible' : 'hidden';
                        });
                    }
                }
            }
            if (tn.startsWith('mcp__orchestra__task_')) {
                _appendToolTechnicalDetails(lastTool, content);
            }
            addTimestamp(lastTool, ts);
            // Панель задач обновляется на ЖИВОМ вызове инструмента. При отрисовке
            // истории те же строки — это прошлое, и каждая из них дёргала бы полную
            // перезагрузку панели: замер по живому дашборду — 8 пар запросов
            if (!_replayingHistory
                && ['mcp__orchestra__task_create','mcp__orchestra__task_update'].includes(tn)) loadTasks();
            return;
        }
        const _orchSimpleResults = {
            'mcp__orchestra__kill_worker': (c) => { const m = c.match(/Worker '(.+?)' stopped/); return m ? { text: `💀 ${m[1]} killed`, color: '#22c55e' } : null; },
            'mcp__orchestra__stop_worker': (c) => { const m = c.match(/Worker '(.+?)' stopped|stopped.*'(.+?)'/i); const n = m?.[1]||m?.[2]; return n ? { text: `⏸️ ${n} stopped`, color: '#22c55e' } : null; },
            'mcp__orchestra__rename_worker': (c) => { const m = c.match(/Worker '(.+?)' renamed to '(.+?)'/); return m ? { text: `✏️ ${m[1]} → ${m[2]}`, color: '#22c55e' } : null; },
            'mcp__orchestra__change_worker_model': (c) => { const m = c.match(/model.*changed|'(.+?)'/i); return { text: '✅ Model changed', color: '#22c55e' }; },
            'mcp__orchestra__update_worker_description': (c) => { const m = c.match(/Description updated for '(.+?)'/); return m ? { text: `✏️ ${m[1]} — description updated`, color: '#22c55e' } : { text: '✅ description updated', color: '#22c55e' }; },
            'mcp__orchestra__merge_worker': (c) => { const m = c.match(/(\d+) commits? merged|Merged/i); return m ? { text: `🔀 Merged${m[1] ? ' ('+m[1]+' commits)' : ''}`, color: '#22c55e' } : null; },
            'mcp__orchestra__send_message': (c) => { const m = c.match(/sent to '(.+?)'/i); return m ? { text: `✅ → ${m[1]}`, color: '#22c55e' } : c.includes('fail') || c.includes('error') || c.includes('Error') ? { text: `❌ ${c.substring(0, 60)}`, color: '#ef4444' } : { text: '✅ Sent', color: '#22c55e' }; },
            'mcp__orchestra__compact_worker': null,
            'mcp__orchestra__list_agents': null,
            'mcp__orchestra__list_orchestrators': null,
            'mcp__orchestra__get_worker_logs': null,
            'mcp__orchestra__bg_create': (c) => { const m = c.match(/Background job created: (\S+)/); return m ? { text: `✅ Job ${m[1].slice(0,12)}`, color: '#22c55e' } : c.includes('rror') ? null : { text: '✅ Job created', color: '#22c55e' }; },
            'mcp__orchestra__bg_cancel': (c) => { const m = c.match(/Job (\S+) cancelled/); return m ? { text: `⏹ ${m[1].slice(0,12)} cancelled`, color: '#94a3b8' } : c.includes('rror') ? null : { text: '⏹ Cancelled', color: '#94a3b8' }; },
        };
        const _orchResultCfg = _orchSimpleResults[lastTool.dataset.toolRawName];
        if (_orchResultCfg !== undefined) {
            const hdr = lastTool.querySelector('.flex.items-center');
            if (typeof _orchResultCfg === 'function') {
                const hasErr = content.includes('failed') || content.includes('Failed') || content.includes('error') || content.includes('Error');
                if (hasErr) {
                    const toolAction = lastTool.dataset.toolRawName.split('__').pop().replace(/_/g, ' ');
                    if (hdr) { hdr.textContent = `❌ ${toolAction} failed`; hdr.style.color = '#ef4444'; }
                    const errEl = document.createElement('div');
                    errEl.style.cssText = 'margin-top:4px;font-size:10px;color:#fca5a5;white-space:pre-wrap;overflow-wrap:anywhere;max-height:54px;overflow-y:hidden;overflow-x:hidden';
                    errEl.textContent = clean;
                    lastTool.appendChild(errEl);
                    if (clean.split('\n').length > 3 || clean.length > 200) {
                        lastTool.style.cursor = 'pointer';
                        let _errExp = false;
                        lastTool.addEventListener('click', (e) => {
                            if (e.target.tagName === 'A') return;
                            _errExp = !_errExp;
                            errEl.style.maxHeight = _errExp ? 'none' : '54px';
                            errEl.style.overflowY = _errExp ? 'visible' : 'hidden';
                        });
                    }
                } else {
                    const result = _orchResultCfg(clean);
                    if (hdr) { hdr.textContent = result?.text || '✅ Done'; hdr.style.color = result?.color || '#22c55e'; }
                }
                addTimestamp(lastTool, ts);
                return;
            }
            if (lastTool.dataset.toolRawName === 'mcp__orchestra__compact_worker') {
                let workerName = '';
                try { const ci = lastTool.dataset.toolContent.indexOf(':'); const cd = JSON.parse(lastTool.dataset.toolContent.slice(ci+1)); workerName = cd.name || ''; } catch {}
                const pctMatch = clean.match(/(\d+)%\s*→\s*(\d+)%/);
                const sumMatch = clean.match(/Summary \((\d+) chars?\):\s*([\s\S]*)/);
                if (hdr && pctMatch) { hdr.textContent = `🗜 ${workerName ? workerName+': ' : ''}${pctMatch[1]}% → ${pctMatch[2]}%`; hdr.style.color = '#22c55e'; }
                else if (hdr) { hdr.textContent = `✅ ${workerName ? workerName+' ' : ''}Compacted`; hdr.style.color = '#22c55e'; }
                if (sumMatch) {
                    const chars = sumMatch[1];
                    const summaryText = sumMatch[2].trim();
                    const charEl = document.createElement('div');
                    charEl.style.cssText = 'font-size:10px;color:#64748b;margin-top:2px';
                    charEl.textContent = `Summary: ${chars} chars`;
                    lastTool.appendChild(charEl);
                    if (summaryText) {
                        const sumEl = document.createElement('div');
                        sumEl.style.cssText = 'font-size:10px;color:#94a3b8;margin-top:2px;max-height:48px;overflow-y:hidden;overflow-x:hidden;white-space:pre-wrap;overflow-wrap:anywhere';
                        sumEl.textContent = summaryText;
                        lastTool.appendChild(sumEl);
                        if (summaryText.split('\n').length > 3 || summaryText.length > 200) {
                            lastTool.style.cursor = 'pointer';
                            let _cExp = false;
                            lastTool.addEventListener('click', (e) => {
                                if (e.target.tagName === 'A') return;
                                _cExp = !_cExp;
                                sumEl.style.maxHeight = _cExp ? 'none' : '48px';
                                sumEl.style.overflowY = _cExp ? 'visible' : 'hidden';
                            });
                        }
                    }
                }
                addTimestamp(lastTool, ts);
                return;
            }
            if (lastTool.dataset.toolRawName === 'mcp__orchestra__list_agents' || lastTool.dataset.toolRawName === 'mcp__orchestra__list_orchestrators') {
                const agentSummary = _agentResultSummary(clean);
                const agentLines = agentSummary?.lines || [];
                if (agentLines.length > 0) {
                    const PREVIEW_COUNT = 4;
                    const container = document.createElement('div');
                    container.style.cssText = 'margin-top:6px;display:flex;flex-direction:column;gap:4px';
                    for (const [i, line] of agentLines.entries()) {
                        const parts = line.split('|').map(p => p.trim());
                        const nameRaw = parts[0] || '';
                        const status = parts[1] || '';
                        const model = parts[2] || '';
                        let ctxRaw = '', taskId = '', desc = '';
                        for (let pi = 3; pi < parts.length; pi++) {
                            const p = parts[pi];
                            if (p.match(/ctx:\d+%/)) ctxRaw = p;
                            else if (p.startsWith('"')) desc = p.replace(/^"|"$/g, '');
                            else if (p && !p.startsWith('$')) taskId = p;
                        }
                        const nameClean = nameRaw.replace(/\*\*/g, '').replace(/^[^\w]*/, '').trim();
                        const icon = nameRaw.match(/[🎯⚙️🔧]/)?.[0] || '⚙️';
                        const ctxPct = parseInt(ctxRaw.match(/(\d+)%/)?.[1] || '0');
                        const ctxColor = ctxPct >= 80 ? '#ef4444' : ctxPct >= 50 ? '#eab308' : '#22c55e';
                        const isRunning = status.includes('running');
                        const row = document.createElement('div');
                        row.style.cssText = `padding:4px 8px;border-radius:6px;background:rgba(30,41,59,0.4);border-left:3px solid ${isRunning ? '#22c55e' : '#334155'}`;
                        if (i >= PREVIEW_COUNT) row.style.display = 'none';
                        row.dataset.agentRow = '1';
                        let h = `<div style="display:flex;align-items:center;gap:6px"><span style="font-size:11px;color:#e2e8f0;font-weight:600">${icon} ${DOMPurify.sanitize(nameClean)}</span><span style="margin-left:auto;font-size:10px;color:${isRunning ? '#22c55e' : '#64748b'}">${DOMPurify.sanitize(status)}</span></div>`;
                        h += `<div style="display:flex;align-items:center;gap:8px;margin-top:2px;font-size:10px;color:#64748b"><span>${DOMPurify.sanitize(model)}</span>`;
                        if (taskId) h += `<span style="color:#a78bfa;font-weight:600">#${DOMPurify.sanitize(taskId.replace(/^[A-Z]+-/, ''))}</span>`;
                        h += `<span style="display:inline-flex;align-items:center;gap:3px">ctx:<span style="color:${ctxColor}">${ctxPct}%</span></span></div>`;
                        if (desc) h += `<div style="font-size:10px;color:#64748b;font-style:italic;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${DOMPurify.sanitize(desc)}</div>`;
                        row.innerHTML = h;
                        container.appendChild(row);
                    }
                    lastTool.appendChild(container);
                    if (hdr) {
                        const counts = agentSummary.counts;
                        hdr.textContent = `🎼 Агенты · ${agentLines.length} всего`;
                        hdr.style.color = counts.broken ? '#ef4444' : counts.waiting ? '#f59e0b' : '#a78bfa';
                    }
                    const counts = agentSummary.counts;
                    const summary = document.createElement('div');
                    summary.dataset.agentSummary = '1';
                    summary.style.cssText = 'margin-top:4px;font-size:10px;color:#94a3b8;display:flex;gap:10px;flex-wrap:wrap';
                    const countText = _agentCountText(counts);
                    summary.innerHTML = `<span style="color:#4ade80">${countText[0]}</span><span style="color:${counts.waiting ? '#f59e0b' : '#64748b'}">${countText[1]}</span><span style="color:${counts.broken ? '#ef4444' : '#64748b'}">${countText[2]}</span>`;
                    lastTool.insertBefore(summary, container);
                    const attention = agentSummary.agents.filter(agent => agent.status === 'waiting' || agent.status === 'broken');
                    if (attention.length) {
                        const attentionEl = document.createElement('div');
                        attentionEl.dataset.agentAttention = '1';
                        attentionEl.style.cssText = 'margin-top:4px;font-size:10px;color:#fbbf24';
                        attentionEl.textContent = `Требуют внимания: ${attention.map(agent => `${agent.name} — ${agent.status}`).join(', ')}`;
                        lastTool.insertBefore(attentionEl, container);
                    }
                    if (agentLines.length > PREVIEW_COUNT) {
                        const hint = document.createElement('div');
                        hint.className = 'text-xs mt-1';
                        hint.style.cssText = 'color:#a78bfa;cursor:pointer;text-align:center';
                        hint.textContent = `▼ ${agentLines.length - PREVIEW_COUNT} more`;
                        lastTool.appendChild(hint);
                        let _alExp = false;
                        lastTool.style.cursor = 'pointer';
                        lastTool.addEventListener('click', (e) => {
                            if (e.target.tagName === 'A') return;
                            _alExp = !_alExp;
                            container.querySelectorAll('[data-agent-row]').forEach((r, i) => {
                                if (i >= PREVIEW_COUNT) r.style.display = _alExp ? 'block' : 'none';
                            });
                            hint.textContent = _alExp ? '▲ collapse' : `▼ ${agentLines.length - PREVIEW_COUNT} more`;
                        });
                    }
                    _appendToolTechnicalDetails(lastTool, content);
                    addTimestamp(lastTool, ts);
                    return;
                }
            }
            if (lastTool.dataset.toolRawName === 'mcp__orchestra__get_worker_logs') {
                const lines = clean.split('\n').filter(l => l.trim());
                let workerName = '';
                try { const ci = lastTool.dataset.toolContent.indexOf(':'); const cd = JSON.parse(lastTool.dataset.toolContent.slice(ci+1)); workerName = cd.name || ''; } catch {}
                if (hdr) { hdr.textContent = `📋 ${workerName ? workerName+': ' : ''}${lines.length} log entries`; hdr.style.color = '#a78bfa'; }
                if (lines.length > 0) {
                    const PREVIEW_LOG = 6;
                    const container = document.createElement('div');
                    container.style.cssText = 'margin-top:4px;display:flex;flex-direction:column;gap:1px';
                    for (const [i, line] of lines.entries()) {
                        const row = document.createElement('div');
                        row.style.cssText = 'font-size:10px;padding:2px 6px;border-radius:3px;color:#cbd5e1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
                        row.dataset.logRow = '1';
                        if (i >= PREVIEW_LOG) row.style.display = 'none';
                        if (line.startsWith('❌')) row.style.color = '#f87171';
                        else if (line.startsWith('👤')) row.style.color = '#818cf8';
                        else if (line.startsWith('🔧')) row.style.color = '#38bdf8';
                        row.textContent = line;
                        row.title = line;
                        container.appendChild(row);
                    }
                    lastTool.appendChild(container);
                    if (lines.length > PREVIEW_LOG) {
                        const hint = document.createElement('div');
                        hint.className = 'text-xs mt-1';
                        hint.style.cssText = 'color:#a78bfa;cursor:pointer;text-align:center';
                        hint.textContent = `▼ ${lines.length - PREVIEW_LOG} more`;
                        lastTool.appendChild(hint);
                        let _logExp = false;
                        lastTool.style.cursor = 'pointer';
                        lastTool.addEventListener('click', (e) => {
                            if (e.target.tagName === 'A') return;
                            _logExp = !_logExp;
                            container.querySelectorAll('[data-log-row]').forEach((r, i) => { if (i >= PREVIEW_LOG) r.style.display = _logExp ? 'block' : 'none'; });
                            hint.textContent = _logExp ? '▲ collapse' : `▼ ${lines.length - PREVIEW_LOG} more`;
                        });
                    }
                }
                addTimestamp(lastTool, ts);
                return;
            }
            const resultEl = document.createElement('div');
            resultEl.className = 'text-xs markdown-body';
            resultEl.style.cssText = 'margin-top:6px;max-height:90px;overflow-y:hidden;overflow-x:hidden;overflow-wrap:anywhere;word-break:break-word;line-height:1.5;color:#cbd5e1';
            resultEl.innerHTML = DOMPurify.sanitize(marked.parse(clean));
            lastTool.appendChild(resultEl);
            const resLines = clean.split('\n');
            if (resLines.length > 5) {
                const hint = document.createElement('div');
                hint.className = 'text-xs mt-1';
                hint.style.cssText = 'color:#38bdf8;cursor:pointer';
                hint.textContent = `▼ ${resLines.length - 5} more lines`;
                lastTool.appendChild(hint);
                let _orchExp = false;
                lastTool.style.cursor = 'pointer';
                lastTool.addEventListener('click', (e) => {
                    if (e.target.tagName === 'A') return;
                    _orchExp = !_orchExp;
                    resultEl.style.maxHeight = _orchExp ? 'none' : '90px';
                    resultEl.style.overflowY = _orchExp ? 'visible' : 'hidden';
                    hint.textContent = _orchExp ? '▲ collapse' : `▼ ${resLines.length - 5} more lines`;
                });
            }
            addTimestamp(lastTool, ts);
            return;
        }
        if (lastTool.dataset.toolRawName === 'Glob') {
            let _globPattern = '';
            try { const _gp = JSON.parse(lastTool.dataset.toolContent.slice(lastTool.dataset.toolContent.indexOf(':') + 1)); _globPattern = _gp.pattern || ''; } catch {}
            const globEl = renderGlobView(_globPattern, clean);
            if (globEl) {
                lastTool.appendChild(globEl);
                const hdr = lastTool.querySelector('.flex.items-center');
                if (hdr) {
                    const count = clean.split('\n').filter(l => l.trim()).length;
                    hdr.textContent = `📂 Glob: ${_globPattern || '?'} (${count})`;
                }
                lastTool.style.cursor = 'pointer';
                lastTool.addEventListener('click', (e) => {
                    if (e.target.tagName === 'A') return;
                    const rest = globEl.querySelector('[data-role="read-rest"]');
                    const more = globEl.querySelector('[data-role="read-more"]');
                    if (rest && more) {
                        const exp = rest.style.display !== 'none';
                        rest.style.display = exp ? 'none' : 'block';
                        const cnt = more.dataset.count;
                        more.textContent = exp ? `▼ ${cnt} more files` : '▲ collapse';
                    }
                });
            } else {
                const noMatch = document.createElement('div');
                noMatch.className = 'text-xs';
                noMatch.style.cssText = 'margin-top:4px;color:#64748b;font-style:italic';
                noMatch.textContent = 'No files found';
                lastTool.appendChild(noMatch);
            }
            addTimestamp(lastTool, ts);
            return;
        }
        if (lastTool.dataset.toolRawName === 'Skill') {
            const resultEl = document.createElement('div');
            resultEl.className = 'text-xs';
            resultEl.style.cssText = 'margin-top:6px;overflow-wrap:anywhere;white-space:pre-wrap;color:#cbd5e1';
            resultEl.textContent = clean.length > 300 ? clean.slice(0, 300) + '…' : clean;
            if (clean.length > 5) lastTool.appendChild(resultEl);
            addTimestamp(lastTool, ts);
            return;
        }
        const isWebFetchResult = lastTool.dataset.toolRawName === 'WebFetch' || lastTool.dataset.toolRawName === 'mcp__websearch__web_fetch';
        if (isWebFetchResult) {
            const bodyEl = document.createElement('div');
            bodyEl.className = 'text-xs markdown-body';
            bodyEl.style.cssText = 'margin-top:6px;line-height:1.5;color:#cbd5e1;max-height:90px;overflow-y:hidden;overflow-x:hidden;overflow-wrap:anywhere;word-break:break-word';
            bodyEl.innerHTML = DOMPurify.sanitize(marked.parse(clean));
            lastTool.appendChild(bodyEl);
            const fetchLines = clean.split('\n');
            if (fetchLines.length > 5) {
                const hint = document.createElement('div');
                hint.className = 'text-xs mt-1';
                hint.style.cssText = 'color:#38bdf8;cursor:pointer';
                hint.textContent = `▼ ${fetchLines.length - 5} more lines`;
                lastTool.appendChild(hint);
                let wfExpanded = false;
                lastTool.style.cursor = 'pointer';
                lastTool.addEventListener('click', (e) => {
                    if (e.target.tagName === 'A') return;
                    wfExpanded = !wfExpanded;
                    bodyEl.style.maxHeight = wfExpanded ? 'none' : '90px';
                    bodyEl.style.overflowY = wfExpanded ? 'visible' : 'hidden';
                    hint.textContent = wfExpanded ? '▲ collapse' : `▼ ${fetchLines.length - 5} more lines`;
                });
            }
            addTimestamp(lastTool, ts);
            return;
        }
        const isWebSearch = lastTool.dataset.toolRawName === 'mcp__websearch__search' ||
                            lastTool.dataset.toolRawName === 'mcp__websearch__search_web' ||
                            lastTool.dataset.toolRawName === 'WebSearch';
        if (isWebSearch) {
            const wsEl = renderWebSearchResults(content);
            if (wsEl) {
                const sep = document.createElement('div');
                sep.className = 'border-t border-slate-700/50 mt-2 pt-2';
                sep.appendChild(wsEl);
                lastTool.appendChild(sep);
                addTimestamp(lastTool, ts);
                return;
            }
        }
        if (lastTool.dataset.isBash) {
            // harness bash (#369) prefixes the result with "exit_code=N" — surface it as a
            // status mark in the header instead of a glued first output line.
            let resText = clean;
            const rcMatch = resText.match(/^exit_code=(-?\d+)[ \t]*\r?\n?/);
            if (rcMatch) {
                const rc = parseInt(rcMatch[1], 10);
                const hdrEl = lastTool.querySelector('.flex.items-center');
                if (hdrEl) {
                    const st = document.createElement('span');
                    st.textContent = rc === 0 ? '✓ 0' : `✗ exit ${rc}`;
                    st.style.cssText = `font-size:10px;font-weight:normal;margin-left:auto;color:${rc === 0 ? '#4ade80' : '#f87171'}`;
                    hdrEl.appendChild(st);
                }
                if (rc === 0) resText = resText.slice(rcMatch[0].length);
            }
            const sep = document.createElement('div');
            sep.className = 'border-t border-slate-700/50 mt-2 pt-2';
            const resLines = resText.split('\n');
            const BASH_PREVIEW = 5;
            const resWrap = document.createElement('div');
            resWrap.className = 'diff-view';
            const previewPre = document.createElement('pre');
            previewPre.style.cssText = 'margin:0;padding:6px 8px;font-size:11px;overflow-x:auto;background:#0d1117;border:none';
            previewPre.textContent = resLines.slice(0, BASH_PREVIEW).join('\n');
            resWrap.appendChild(previewPre);
            if (resLines.length > BASH_PREVIEW) {
                const restPre = document.createElement('pre');
                restPre.style.cssText = 'margin:0;padding:0 8px 6px;font-size:11px;overflow-x:auto;background:#0d1117;border:none;display:none';
                restPre.dataset.role = 'bash-result';
                restPre.textContent = resLines.slice(BASH_PREVIEW).join('\n');
                resWrap.appendChild(restPre);
                const resHint = document.createElement('div');
                resHint.className = 'diff-file';
                resHint.dataset.role = 'bash-result-hint';
                resHint.dataset.count = resLines.length - BASH_PREVIEW;
                resHint.style.cssText = 'cursor:pointer;text-align:center;color:#38bdf8;font-size:10px';
                resHint.textContent = `▼ ${resLines.length - BASH_PREVIEW} more lines`;
                resWrap.appendChild(resHint);
            }
            sep.appendChild(resWrap);
            lastTool.appendChild(sep);
            addTimestamp(lastTool, ts);
            return;
        }
        if (lastTool.dataset.isGrep) {
            const grepEl = renderGrepResults(clean, lastTool.dataset.grepPattern);
            if (grepEl) {
                lastTool.appendChild(grepEl);
                lastTool.style.cursor = 'pointer';
                lastTool.addEventListener('click', () => {
                    const restEl = grepEl.querySelector('[data-role="read-rest"]');
                    const moreEl = grepEl.querySelector('[data-role="read-more"]');
                    if (restEl && moreEl) {
                        const showing = restEl.style.display !== 'none';
                        restEl.style.display = showing ? 'none' : 'block';
                        moreEl.textContent = showing ? `▼ ${moreEl.dataset.count} more lines` : `▲ collapse`;
                    }
                });
            }
            addTimestamp(lastTool, ts);
            return;
        }
        if (lastTool.dataset.isRead) {
            delete lastTool.dataset.lastTool;
            const readContainer = lastTool.querySelector('.diff-view');
            if (readContainer) {
                const skeletonEl = readContainer.querySelector('[data-role="read-skeleton"]');
                if (skeletonEl) skeletonEl.remove();
                const readPath = readContainer.dataset.readPath || '';
                if (/\.md$/i.test(readPath)) {
                    const mdClean = clean.replace(/^\s*\d+\t/gm, '');
                    readContainer.style.overflowX = 'hidden';
                    readContainer.style.maxWidth = '100%';
                    const mdEl = document.createElement('div');
                    mdEl.className = 'markdown-body';
                    mdEl.style.cssText = 'padding:6px 8px;font-size:11px;overflow-wrap:anywhere;word-break:break-word;overflow-x:hidden;max-width:100%;max-height:90px;overflow-y:hidden';
                    mdEl.innerHTML = DOMPurify.sanitize(marked.parse(mdClean), {ADD_TAGS: ['input'], ADD_ATTR: ['checked', 'disabled', 'type']});
                    const MD_PREVIEW_H = 90;
                    readContainer.appendChild(mdEl);
                    const moreEl = document.createElement('div');
                    moreEl.className = 'diff-file';
                    moreEl.dataset.role = 'read-more';
                    moreEl.dataset.count = '0';
                    moreEl.style.cssText = 'cursor:pointer;text-align:center;color:#38bdf8;font-size:10px';
                    moreEl.textContent = '▼ more';
                    readContainer.appendChild(moreEl);
                    requestAnimationFrame(() => {
                        if (mdEl.scrollHeight <= MD_PREVIEW_H + 4) {
                            moreEl.style.display = 'none';
                            mdEl.style.maxHeight = 'none';
                            mdEl.style.overflowY = 'visible';
                        }
                    });
                    let mdExpanded = false;
                    const toggleMd = () => {
                        mdExpanded = !mdExpanded;
                        mdEl.style.maxHeight = mdExpanded ? 'none' : MD_PREVIEW_H + 'px';
                        mdEl.style.overflowY = mdExpanded ? 'visible' : 'hidden';
                        moreEl.textContent = mdExpanded ? '▲ collapse' : '▼ more';
                    };
                    lastTool.style.cursor = 'pointer';
                    lastTool.addEventListener('click', (e) => { if (e.target.tagName !== 'A') toggleMd(); });
                    addTimestamp(lastTool, ts);
                    return;
                }
                if (/\.(png|jpg|jpeg|gif|webp|svg)$/i.test(readPath)) {
                    const img = document.createElement('img');
                    img.src = `/api/files/raw?path=${encodeURIComponent(readPath)}&t=${Date.now()}`;
                    img.loading = 'lazy';
                    img.style.cssText = 'max-height:200px;border-radius:8px;cursor:pointer;margin-top:6px;display:block';
                    img.addEventListener('click', () => openImageLightbox(img.src));
                    readContainer.appendChild(img);
                    addTimestamp(lastTool, ts);
                    return;
                }
                const lines = clean.split('\n').map(l => l.length > 200 ? l.slice(0, 200) + '…' : l);
                const PREVIEW = 5;
                const previewL = lines.slice(0, PREVIEW);
                const restL = lines.slice(PREVIEW);
                for (const line of previewL) {
                    readContainer.appendChild(_diffContextLine(line));
                }
                if (restL.length > 0) {
                    const restEl = document.createElement('div');
                    restEl.dataset.role = 'read-rest';
                    restEl.style.display = 'none';
                    for (const line of restL) {
                        restEl.appendChild(_diffContextLine(line));
                    }
                    readContainer.appendChild(restEl);
                    const moreEl = document.createElement('div');
                    moreEl.className = 'diff-file';
                    moreEl.dataset.role = 'read-more';
                    moreEl.dataset.count = restL.length;
                    moreEl.style.cssText = 'cursor:pointer;text-align:center;color:#38bdf8;font-size:10px';
                    moreEl.textContent = `▼ ${restL.length} more lines`;
                    readContainer.appendChild(moreEl);
                }
            }
            addTimestamp(lastTool, ts);
            return;
        }
        let _resultJsonParsed = null;
        try { _resultJsonParsed = JSON.parse(content); } catch {}
        if (_resultJsonParsed && typeof _resultJsonParsed === 'object' && !Array.isArray(_resultJsonParsed)) {
            let data = _resultJsonParsed;
            if (data.result !== undefined && Object.keys(data).length === 1) {
                if (typeof data.result === 'string') {
                    try { data = JSON.parse(data.result); } catch { data = null; }
                } else if (typeof data.result === 'object' && data.result !== null) {
                    data = data.result;
                } else { data = null; }
            }
            if (data && typeof data === 'object' && !Array.isArray(data)) {
                const hdr = lastTool.querySelector('.flex.items-center');
                const hasErr = data.error || data.Error;
                if (hdr && hasErr) {
                    hdr.textContent = `❌ ${DOMPurify.sanitize(String(data.error || data.Error)).slice(0, 80)}`;
                    hdr.style.color = '#ef4444';
                } else if (hdr && !hdr.textContent.includes('✅') && !hdr.textContent.includes('❌')) {
                    hdr.textContent = hdr.textContent.replace(/⏳.*$/, '✅ Done');
                }
                lastTool.dataset.toolContent += '\n\n' + content;
                const gridWrap = document.createElement('div');
                gridWrap.style.cssText = 'margin-top:4px';
                _renderJsonGrid(data, gridWrap);
                lastTool.appendChild(gridWrap);
                addTimestamp(lastTool, ts);
                return;
            }
        }
        lastTool.dataset.toolContent += '\n\n' + content;
        const oldCopy = lastTool.querySelector('.copy-btn');
        if (oldCopy) oldCopy.remove();
        addCopyBtn(lastTool, lastTool.dataset.toolContent);

        const resultEl = document.createElement('div');
        resultEl.className = 'text-xs result-body';
        resultEl.style.cssText = 'white-space:pre-wrap;margin-top:6px';
        resultEl.innerHTML = '📎 ' + DOMPurify.sanitize(preview, {ADD_ATTR: ['target']});
        lastTool.appendChild(resultEl);
        if (full) {
            const rHint = document.createElement('div');
            rHint.className = 'text-xs mt-1 result-hint';
            rHint.style.cssText = 'color:#38bdf8;cursor:pointer';
            rHint.textContent = `▼ ${_resultLines.length - _RESULT_PREVIEW} more lines`;
            lastTool.appendChild(rHint);
            let rExpanded = false;
            const toggleResult = () => {
                rExpanded = !rExpanded;
                resultEl.innerHTML = '📎 ' + DOMPurify.sanitize(rExpanded ? full : preview, {ADD_ATTR: ['target']});
                rHint.textContent = rExpanded ? '▲ collapse' : `▼ ${_resultLines.length - _RESULT_PREVIEW} more lines`;
            };
            lastTool.addEventListener('click', (e) => { if (e.target.tagName !== 'A') toggleResult(); });
        }
        addTimestamp(lastTool, ts);
        return;
    }

    const wsStandalone = renderWebSearchResults(content);
    if (wsStandalone) {
        const sep = document.createElement('div');
        sep.className = 'border-t border-slate-700/50 mt-2 pt-2';
        sep.appendChild(wsStandalone);
        div.appendChild(sep);
        addTimestamp(div, ts);
        _insertAndFollow(div);
        return;
    }

    let _standaloneJson = null;
    try { _standaloneJson = JSON.parse(content); } catch {}
    if (_standaloneJson && typeof _standaloneJson === 'object' && !Array.isArray(_standaloneJson)) {
        let sData = _standaloneJson;
        if (sData.result !== undefined && Object.keys(sData).length === 1) {
            if (typeof sData.result === 'string') { try { sData = JSON.parse(sData.result); } catch { sData = null; } }
            else if (typeof sData.result === 'object' && sData.result !== null) sData = sData.result;
            else sData = null;
        }
        if (sData && typeof sData === 'object' && !Array.isArray(sData)) {
            const gridWrap = document.createElement('div');
            gridWrap.style.cssText = 'margin-top:4px';
            _renderJsonGrid(sData, gridWrap);
            div.appendChild(gridWrap);
            addTimestamp(div, ts);
            _insertAndFollow(div);
            return;
        }
    }
    const resultBody = document.createElement('div');
    resultBody.style.whiteSpace = 'pre-wrap';
    resultBody.innerHTML = '📎 ' + DOMPurify.sanitize(preview, {ADD_ATTR: ['target']});
    div.appendChild(resultBody);
    if (full) {
        const sHint = document.createElement('div');
        sHint.className = 'text-xs mt-1';
        sHint.style.cssText = 'color:#38bdf8;cursor:pointer';
        sHint.textContent = `▼ ${_resultLines.length - _RESULT_PREVIEW} more lines`;
        div.appendChild(sHint);
        let sExpanded = false;
        const toggleStandalone = () => {
            sExpanded = !sExpanded;
            resultBody.innerHTML = '📎 ' + DOMPurify.sanitize(sExpanded ? full : preview, {ADD_ATTR: ['target']});
            sHint.textContent = sExpanded ? '▲ collapse' : `▼ ${_resultLines.length - _RESULT_PREVIEW} more lines`;
        };
        div.style.cursor = 'pointer';
        div.addEventListener('click', (e) => { if (e.target.tagName !== 'A') toggleStandalone(); });
    }
    return div;
}

// Central renderer for all log entry types (text, tool, tool_result, stream, user_message, etc.)
// anchor = insert before this node instead of appending — used by loadMoreLogs for prepend
// payload = full SSE log object (carries subagent_id for sub-agent nesting)
function addChatEntry(type, content, ts, anchor, payload) {
    if (_isSilentTurnMarker(type, content)) return;
    if (HIDE_THINKING && (type === 'thinking' || type === 'thinking_stream')) return;
    // Live sub-agent output → nest inside the sub-agent accordion, not the main flow
    if ((type === 'subagent_stream' || type === 'subagent_event') && payload && payload.subagent_id) {
        appendSubagentLog(payload.subagent_id, payload.event_type || 'stream', content);
        return;
    }
    if (type !== 'user_message' && type !== 'stream') removeWaitingIndicator();
    const chat = $('#chat');
    let _insertedBeforeStream = false;
    const _insert = (el) => {
        _tagChatTimelineNode(el, type, ts);
        _stampChatLogNode(el, payload);
        if (payload && payload.trunc) _attachTruncNotice(el, payload, type, ts);
        if (anchor) return chat.insertBefore(el, anchor);
        const wasAtBottom = _chatAtBottom(chat);
        let inserted;
        if (streamBubble && streamBubble.parentNode === chat) {
            _insertedBeforeStream = true;
            inserted = chat.insertBefore(el, streamBubble);
        } else {
            inserted = chat.appendChild(el);
        }
        if (!scrollAfterLoad && !wasAtBottom) _markChatHasNewBelow();
        return inserted;
    };
    const _insertAndFollow = (el, afterInsert) => {
        const wasAtBottom = _chatAtBottom(chat);
        const inserted = _insert(el);
        if (afterInsert) afterInsert(inserted);
        if (!anchor && !_insertedBeforeStream && wasAtBottom) chat.scrollTop = chat.scrollHeight;
        return inserted;
    };

    // Heuristic: detect base64 image payloads from tool results (e.g. screenshot tools)
    const _isBase64Image = content.includes("'type': 'image'") || content.includes('"type": "image"') || content.includes('"type":"image"') || /['"]?data['"]?\s*[:=]\s*['"][A-Za-z0-9+/=\s]{500,}['"]/.test(content);

    if (type === 'thinking_stream') {
        const activity = (payload && payload.activity) || 'reasoning';
        const key = `${activity}:${(payload && payload.item_id) || ''}`;
        if (!_codexThinkingLive || _codexThinkingKey !== key) {
            _removeCodexThinkingLive();
            _codexThinkingLive = document.createElement('div');
            _codexThinkingLive.className = 'codex-activity-card codex-thinking-live';
            _codexThinkingLive.dataset.activity = activity;
            const label = document.createElement('div');
            label.className = 'codex-live-label';
            label.textContent = activity === 'plan'
                ? '▦ Planning live'
                : activity === 'waiting'
                    ? '⌁ Codex still working'
                    : '◇ Reasoning live';
            const body = document.createElement('div');
            body.className = 'codex-live-thinking-body';
            _codexThinkingLive.append(label, body);
            _codexThinkingKey = key;
            _insert(_codexThinkingLive);
        }
        const body = _codexThinkingLive.querySelector('.codex-live-thinking-body');
        body.textContent = activity === 'waiting'
            ? content
            : (body.textContent + content).slice(-30_000);
        return;
    }

    if (type === 'tool_stream' || type === 'tool_patch') {
        _queueOrApplyCodexToolUpdate(chat, type, content, payload, anchor);
        return;
    }

    if (type === 'turn_diff') {
        const patch = renderCodexFileChange({
            changes: [{path: 'Current turn', kind: 'update', diff: content}],
        });
        if (!_codexTurnDiffBubble) {
            _codexTurnDiffBubble = document.createElement('div');
            _codexTurnDiffBubble.className = 'codex-activity-card codex-turn-diff';
            const title = document.createElement('div');
            title.className = 'codex-live-label';
            title.textContent = '± Live turn diff';
            _codexTurnDiffBubble.appendChild(title);
            _insert(_codexTurnDiffBubble);
        }
        const old = _codexTurnDiffBubble.querySelector('.codex-file-change');
        if (old && patch) old.replaceWith(patch);
        else if (patch) _codexTurnDiffBubble.appendChild(patch);
        return;
    }

    if (_isBase64Image && type !== 'tool' && type !== 'tool_result') {
        const div = document.createElement('div');
        div.className = 'px-3 py-2 rounded-lg text-sm break-words chat-bot';
        const b64Match = content.match(/['"]?data['"]?\s*[:=]\s*['"]([A-Za-z0-9+/=\s]{500,})['"]/);
        if (b64Match && !(payload && payload.trunc)) {
            const img = document.createElement('img');
            img.src = 'data:image/png;base64,' + b64Match[1].replace(/\s/g, '');
            img.style.cssText = 'max-width:100%;max-height:300px;border-radius:6px;cursor:pointer';
            img.addEventListener('click', () => _showImageOverlay(img.src));
            div.appendChild(img);
        } else {
            div.textContent = '🖼 [Image]';
            div.style.color = '#64748b';
        }
        addTimestamp(div, ts);
        _insertAndFollow(div);
        return;
    }

    if (_renderCompactToolEntry(type, content, ts, payload, chat, anchor, _insertAndFollow, _isBase64Image)) return;

    // Stream events feed the typewriter buffer — RAF loop renders incrementally
    if (type === 'stream') {
        removeWaitingIndicator();
        if (_rateLimitAgent) _hideRateLimitBanner();  // agent resumed → rate limit cleared
        if (!streamBubble) {
            streamBubble = document.createElement('div');
            streamBubble.className = 'px-3 py-2 rounded-lg text-sm break-words chat-bot markdown-body streaming';
            streamBubble.style.position = 'relative';
            const agentColor = agentColors[selectedAgent];
            if (agentColor) streamBubble.style.borderLeft = `3px solid ${agentColor}`;
            _insert(streamBubble);
            if (typeof _recomputeChatTimelineFinals === 'function') _recomputeChatTimelineFinals();
            if (typeof _syncChatTimelineControls === 'function') _syncChatTimelineControls();
            _streamLastParse = 0;
        }
        streamPending += content;
        if (!_streamRafId) _streamRafId = requestAnimationFrame(_streamRenderTick);
        return;
    }

    // 'text' event signals streaming finished — flush typewriter buffer,
    // replace with authoritative DB content, finalize with copy/timestamp.
    if (type === 'text') {
        if (streamBubble) {
            _stampChatLogNode(streamBubble, payload);
            _completeStreamBubble(content, ts);
            _scheduleChatReadCapture();
            return;
        }
        // Stream already closed (e.g. status `turn ended` raced ahead of this row) with
        // the same body — skip the second paint. History reload has no streamBubble and
        // content differs from any prior live finalize, so it still creates a bubble.
        if (content && content === _lastFinalizedStreamText) {
            _lastFinalizedStreamText = '';
            _scheduleChatReadCapture();
            return;
        }
        // No live stream (history, or runtime that only emits final text) → fall through
        // to the normal chat-bot bubble renderer below.
    }

    if (type === 'thinking') {
        _removeCodexThinkingLive('reasoning');
        const card = _renderCodexThinking(content, '◇ Reasoning');
        addTimestamp(card, ts);
        _insert(card);
        return;
    }

    if (type === 'plan') {
        _removeCodexThinkingLive('plan');
        const card = _renderCodexPlan(content);
        addTimestamp(card, ts);
        _insert(card);
        return;
    }

    const platformNotice = renderSystemChatEntry(type, content, ts);
    if (platformNotice) {
        _insert(platformNotice);
        return;
    }

    if (type === 'review') {
        let reviewData = {};
        try { reviewData = JSON.parse(content); } catch {}
        const review = document.createElement('div');
        review.className = 'codex-review';
        const phase = reviewData.phase === 'exited' ? 'Review completed' : 'Review mode';
        review.innerHTML = `<div class="codex-review-title">◎ ${phase}</div><div class="codex-review-body"></div>`;
        review.querySelector('.codex-review-body').textContent = reviewData.review || '';
        addTimestamp(review, ts);
        _insert(review);
        return;
    }

    if (_renderStatusEntry(type, content, ts, anchor, _insertAndFollow, payload)) return;

    if (_renderSubagentLifecycleEntry(type, content, ts, payload, chat, _insertAndFollow)) return;

    const div = document.createElement('div');
    div.className = `px-3 py-2 rounded-lg text-sm break-words ${
        type === 'user_message' ? 'chat-user ml-16' :
        type === 'tool' ? 'chat-tool' :
        type === 'tool_result' ? 'chat-tool-result' :
        type === 'error' ? 'text-red-400 text-xs' :
        'chat-bot markdown-body'
    }`;
    if (type === 'user_message') {
        const allowedOrigins = new Set([
            'user', 'agent', 'background_task', 'platform', 'system', 'unknown',
        ]);
        const suppliedOrigin = payload && payload.origin;
        const suppliedDetail = payload && payload.origin_detail;
        const suppliedSenders = suppliedDetail && suppliedDetail.senders;
        const detailKeys = suppliedDetail && typeof suppliedDetail === 'object'
            ? Object.keys(suppliedDetail)
            : [];
        const validOptionalText = value => value === undefined
            || (typeof value === 'string' && (value === '' || Boolean(value.trim())));
        const validDetail = suppliedDetail
            && typeof suppliedDetail === 'object'
            && !Array.isArray(suppliedDetail)
            && detailKeys.every(key => ['senders', 'subtype', 'ref'].includes(key))
            && Array.isArray(suppliedSenders)
            && suppliedSenders.length > 0
            && suppliedSenders.every(sender => typeof sender === 'string' && sender.trim())
            && validOptionalText(suppliedDetail.subtype)
            && validOptionalText(suppliedDetail.ref);
        const validOrigin = allowedOrigins.has(suppliedOrigin);
        const origin = validOrigin && validDetail ? suppliedOrigin : 'unknown';
        const senders = validOrigin && validDetail
            ? suppliedSenders.map(sender => sender.trim())
            : ['unknown'];
        if (origin === 'user') {
            div.className += ' markdown-body';
            div.innerHTML = DOMPurify.sanitize(marked.parse(content));
            renderImages(div, content);
        } else {
            const originLabels = {
                agent: 'Agent',
                background_task: 'Background task',
                platform: 'Platform',
                system: 'System',
                unknown: 'Unknown',
            };
            const senderColor = _senderColor(senders[0]);
            div.dataset.from = senders.join(', ');
            div.dataset.origin = origin;
            div.style.borderLeft = `3px solid ${senderColor}`;
            div.className = 'px-3 py-2 rounded-lg text-sm break-words chat-bot';
            const label = document.createElement('div');
            label.className = 'text-xs mb-1 chat-from-label';
            label.style.color = senderColor;
            label.textContent = `${originLabels[origin]}: ${senders.join(', ')} → ${selectedAgent}`;
            div.appendChild(label);
            const body = document.createElement('div');
            body.className = 'markdown-body';
            body.innerHTML = DOMPurify.sanitize(marked.parse(content));
            div.appendChild(body);
            renderImages(body, content);
        }
    }
    else if (type === 'tool') {
        _renderFullToolCall(content, payload, div);
    }
    else if (type === 'tool_result') {
        if (!_renderFullToolResult(content, ts, payload, anchor, div, _insertAndFollow, _isBase64Image)) return;
    }
    else if (type === 'error') {
        if (/rate.?limit/i.test(content)) {
            div.textContent = '⏳ Rate limit — Anthropic временно ограничил запросы (это НЕ лимит твоей подписки). Orchestra автоматически повторит.';
            div.className = div.className.replace('text-red-400', 'text-amber-400');
        } else {
            div.textContent = content;
        }
    }
    else {
        div.innerHTML = DOMPurify.sanitize(marked.parse(content));
        _markUnexecutedToolCall(div, content);
        const agentColor = agentColors[selectedAgent];
        if (agentColor) div.style.borderLeft = `3px solid ${agentColor}`;
        renderImages(div, content);
    }

    addCopyBtn(div, content);
    addTimestamp(div, ts);
    _insertAndFollow(div, () => {
        _trimChatNodes(chat);
        if (type === 'tool') _adoptOrphanResults(chat, div.dataset.toolUseId);
    });
}
