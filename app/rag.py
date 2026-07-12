"""RAG semantic memory для Orchestra — FastEmbed (bge-m3 int8 ONNX) + sqlite-vec hybrid search.

Портирован из kesha-tg-bot/rag.py. Отличия от kesha:
- диалоговый слой (vec_messages / messages.db ATTACH) ВЫКИНУТ — у Orchestra нет TG-диалогов;
- добавлен `project` namespace (scope репозитория) — изоляция между 17 разнородными проектами;
- логи агентов (`user_message` / `text` из orchestra.db) индексируются отдельным слоем vec_logs,
  self-contained (текст копируется в log_chunks, без ATTACH orchestra.db → устойчиво к её миграциям).

ВСЕ методы RagMemory вызываются ТОЛЬКО из executor'ов (write / read, каждый max_workers=1).
Коннект sqlite и embedder привязаны к потоку — не дёргать из других потоков (SQLite не thread-safe).
"""

import logging
import re
import struct
from pathlib import Path

# NB: sqlite_vec / fastembed / onnxruntime are OPTIONAL deps (`orchestra[rag]`). They are
# imported LAZILY inside RagMemory.__init__ / _get_embedder — so pure-logic functions
# (chunkers, _classify_log, _rrf, file_change_target) and `import app.rag` work WITHOUT them.

logger = logging.getLogger("orchestra.rag")

DB_PATH = Path("./data/vec.db")
# bge-m3 int8 ONNX: separation margin +0.237 vs e5-small +0.055 (kesha-замер на абстрактных запросах).
# Single-file model_quantized.onnx — fp32 с external onnx_data падает в ORT.
# MODEL_NAME ≠ нативному имени FastEmbed, иначе add_custom_model пропустится → fp32 → краш.
MODEL_NAME = "AlpEge/bge-m3-onnx-int8"
MODEL_HF = "AlpEge/bge-m3-onnx-int8"
MODEL_FILE = "model_quantized.onnx"
DIM = 1024
MODEL_PREFIX = False  # bge-m3: CLS-пулинг, без query:/passage: префиксов. E5-модели → True.
MODEL_POOLING = "cls"  # bge-m3 = CLS. E5 = mean.
RRF_K = 60
# bump при ЛЮБОМ изменении схемы vec/fts → старые таблицы дропаются и ребилдятся из backfill.
# v1: файлы (vec_files) + логи (vec_logs) с project namespace. Индекс производный, дроп безопасен.
SCHEMA_VERSION = 1
POOL_MULT = 4  # candidate pool = limit * POOL_MULT перед RRF

# Chunking длинных текстов. В символах (~4 символа/токен рус.), без tiktoken.
CHUNK_CHAR_LIMIT = 1200   # ~300 токенов — выше этого режем
CHUNK_SIZE = 800          # ~200 токенов на кусок
CHUNK_OVERLAP = 200       # ~50 токенов перекрытие
CHUNK_STRIDE = 1000       # макс чанков на источник (chunk_id = source_id*STRIDE + idx)
EMBED_BATCH = 16          # research §6: batch=16 → peak 1.6GB (vs 2.4GB@64) — RAM-митигация

# Файловая индексация. Только markdown-проза: .md.
# xml/csv/json/html = машинные данные/логи → мусор в retrieval (kesha-замер).
FILE_EXTENSIONS = {".md"}
EXCLUDED_DIRS = {".git", ".claude", ".gemini", ".kiro", ".github", ".serena",
                 ".claude-plugin", "node_modules", "__pycache__", ".venv", "worktrees"}
# codex-review-*.md = дебаты до 406KB, шум > сигнал (plan §0) → блэклист по имени.
EXCLUDED_FILE_RE = re.compile(r"codex-review.*\.md$")
# md heading-aware: секция > MD_MAX режем по параграфам, секция < MD_MIN мержим с соседней.
MD_MAX_CHUNK = 1500
MD_MIN_MERGE = 250
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")

# Логи: индексируем только эти типы (plan §0 — 94% байт логов = tool_result/tool = машинный шум).
LOG_TYPES = ("user_message", "text")
MIN_LOG_LEN = 200  # порог для user_msg/text (нарратив <100 симв = tool-шум). agent_msg — без порога.
_FROM_RE = re.compile(r"^\[from:([^\]]+)\]")  # inter-agent send_message префикс


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _split_oversized(words: list[str]) -> list[str]:
    """Слово длиннее CHUNK_SIZE (URL/base64/blob) → режем char-окном, иначе обходит лимит."""
    out = []
    for w in words:
        if len(w) > CHUNK_SIZE:
            out.extend(w[i:i + CHUNK_SIZE] for i in range(0, len(w), CHUNK_SIZE))
        else:
            out.append(w)
    return out


def _chunk(content: str) -> list[str]:
    """Длинный content → куски ~CHUNK_SIZE символов с overlap. Короткий → [content].
    Жёсткий cap CHUNK_STRIDE-1 чанков (chunk_id = source*STRIDE+idx не должен пересечь следующий)."""
    if len(content) <= CHUNK_CHAR_LIMIT:
        return [content]
    words = _split_oversized(content.split())
    chunks, cur, cur_len = [], [], 0
    for w in words:
        cur.append(w)
        cur_len += len(w) + 1
        if cur_len >= CHUNK_SIZE:
            chunks.append(" ".join(cur))
            # overlap: оставить хвост слов на ~CHUNK_OVERLAP символов.
            keep, klen = [], 0
            for tw in reversed(cur):
                if klen + len(tw) + 1 > CHUNK_OVERLAP:
                    break
                keep.insert(0, tw)
                klen += len(tw) + 1
            cur, cur_len = keep, klen
    if cur and (not chunks or " ".join(cur) != chunks[-1]):
        chunks.append(" ".join(cur))
    return chunks[:CHUNK_STRIDE - 1]


def _split_paragraphs(text: str, max_chunk: int) -> list[str]:
    """Режем по двойному \\n, набирая параграфы до max_chunk. Параграф длиннее max_chunk
    отдаём как есть (char-cap применит _chunk выше по стеку)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if cur and len(cur) + len(p) + 2 > max_chunk:
            chunks.append(cur.strip())
            cur = ""
        cur = (cur + "\n\n" + p) if cur else p
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def _chunk_markdown(content: str) -> list[str]:
    """Heading-aware: секция под заголовком = кусок, с хлебной крошкой (Physics > Thermo).
    Большая секция → делим по параграфам, крошечная → копим с соседней. Без заголовков → параграфы.
    Крошка даёт контекст изолированному чанку (иначе '- КПД 300%' без темы)."""
    if not content or not content.strip():
        return []
    lines = content.split("\n")
    sections: list[tuple[str, str]] = []
    stack: list[tuple[int, str]] = []
    buf: list[str] = []
    crumb = ""

    def flush():
        text = "\n".join(buf).strip()
        if text:
            sections.append((crumb, text))

    for line in lines:
        m = _HEADING_RE.match(line)
        if m:
            flush()
            buf.clear()
            level = len(m.group(1))
            title = m.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            crumb = " > ".join(t for _, t in stack)
        buf.append(line)
    flush()

    if not sections:  # без заголовков → параграфы, фолбэк на char-window
        return _split_paragraphs(content, MD_MAX_CHUNK) or _chunk(content)

    chunks: list[str] = []
    pending = ""
    for crumb, text in sections:
        block = text
        if len(text) > MD_MAX_CHUNK:
            if pending:
                chunks.append(pending.strip())
                pending = ""
            chunks.extend(_split_paragraphs(block, MD_MAX_CHUNK))
            continue
        if pending and len(pending) + len(block) + 2 > MD_MAX_CHUNK:
            chunks.append(pending.strip())
            pending = block
        else:
            pending = (pending + "\n\n" + block) if pending else block
        if len(pending) >= MD_MIN_MERGE:
            chunks.append(pending.strip())
            pending = ""
    if pending.strip():
        chunks.append(pending.strip())
    return chunks[:CHUNK_STRIDE - 1]


def _chunk_file(path: str, content: str) -> list[str]:
    """Диспетчер по расширению. .md → heading-aware, иначе char-window. Пустой → []."""
    if not content or not content.strip():
        return []
    ext = Path(path).suffix.lower()
    if ext == ".md":
        chunks = _chunk_markdown(content)
    else:
        chunks = _chunk(content)
    # финальный char-cap: параграф длиннее MD_MAX не должен уйти гигантским вектором
    out: list[str] = []
    for c in chunks:
        out.extend(_chunk(c) if len(c) > CHUNK_CHAR_LIMIT else [c])
    return out[:CHUNK_STRIDE - 1]


def file_change_target(abs_path: str, root: Path) -> str | None:
    """Абсолютный путь → относительный (от root) если файл подлежит индексации, иначе None.
    Фильтрует по расширению, EXCLUDED_DIRS и EXCLUDED_FILE_RE. Чистая функция для watcher/тестов."""
    root = root.resolve()
    p = Path(abs_path)
    if p.suffix.lower() not in FILE_EXTENSIONS:
        return None
    if EXCLUDED_FILE_RE.search(p.name):
        return None
    try:
        rel = p.resolve().relative_to(root)
    except ValueError:
        return None  # вне проекта
    if any(part in EXCLUDED_DIRS for part in rel.parts):
        return None
    return str(rel)


def _classify_log(log_type: str, content: str) -> tuple[str, str | None]:
    """Тип+контент лога → (kind, author). user_message с [from:X] = inter-agent send_message
    (высочайший сигнал, plan §0), без префикса = человек, text = ответ агента."""
    if log_type == "user_message":
        m = _FROM_RE.match(content or "")
        if m:
            return "agent_msg", m.group(1).strip()
        return "user_msg", None
    return "text", None  # log_type == "text"


_embedder = None
_embedder_lock = None  # threading.Lock, lazy (не тащим threading в импорт если RAG выключен)


def _get_embedder():
    """Module-level singleton embedder, ОБЩИЙ для всех RagMemory-инстансов (write+read потоки).
    ONNX InferenceSession thread-safe → один экземпляр обслуживает оба потока без +946MB RAM.
    Загрузка под локом (двойная проверка) — гонка на первом обращении из двух потоков."""
    global _embedder, _embedder_lock
    if _embedder is not None:
        return _embedder
    if _embedder_lock is None:
        import threading
        _embedder_lock = threading.Lock()
    with _embedder_lock:
        if _embedder is not None:
            return _embedder
        import onnxruntime as _ort
        _orig_sess = _ort.InferenceSession.__init__
        def _patched_init(self_sess, *a, **k):
            so = k.get("sess_options") or _ort.SessionOptions()
            so.enable_cpu_mem_arena = False
            so.enable_mem_pattern = False
            k["sess_options"] = so
            _orig_sess(self_sess, *a, **k)
        _ort.InferenceSession.__init__ = _patched_init
        from fastembed import TextEmbedding
        from fastembed.common.model_description import PoolingType, ModelSource
        if MODEL_NAME not in {m["model"] for m in TextEmbedding.list_supported_models()}:
            pooling = PoolingType.CLS if MODEL_POOLING == "cls" else PoolingType.MEAN
            TextEmbedding.add_custom_model(
                model=MODEL_NAME, pooling=pooling, normalization=True,
                sources=ModelSource(hf=MODEL_HF), dim=DIM, model_file=MODEL_FILE,
            )
        _embedder = TextEmbedding(model_name=MODEL_NAME)
        logger.info(f"RAG embedder loaded (shared): {MODEL_NAME}")
    return _embedder


class RagMemory:
    def __init__(self, path: Path = DB_PATH, readonly: bool = False):
        import sqlite3

        import sqlite_vec  # optional dep — imported here so pure-logic works without it

        self.readonly = readonly
        path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=True (default) — каждый instance живёт в одном executor-потоке.
        # readonly: коннект в ?mode=ro к той же WAL-БД → конкурентное чтение во время записи.
        if readonly:
            self.conn = sqlite3.connect(f"file:{path}?mode=ro", isolation_level=None, uri=True)
        else:
            self.conn = sqlite3.connect(str(path), isolation_level=None, uri=True)
        self.conn.row_factory = sqlite3.Row
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)
        if not readonly:
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")  # ro-читатель ждёт, не падает, на checkpoint
        if not readonly:
            self._create_schema()

    def _create_schema(self) -> None:
        # схема изменилась (или alpha-формат sqlite-vec) → дроп + ребилд из backfill.
        # CREATE ... IF NOT EXISTS НЕ мигрирует существующую таблицу — поэтому версионируем.
        ver = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if ver != SCHEMA_VERSION:
            for t in ("vec_files", "fts_files", "file_chunks", "files",
                      "vec_logs", "fts_logs", "log_chunks", "logs_indexed"):
                self.conn.execute(f"DROP TABLE IF EXISTS {t}")
            self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            if ver != 0:
                logger.info(f"RAG schema v{ver}→v{SCHEMA_VERSION}: dropped index, rebuild via backfill")
        # --- файлы: метаданные + дедуп (sha256 по контенту, path относительный, project namespace).
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS files (
                file_id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                path TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                mtime REAL NOT NULL,
                UNIQUE(project, path)
            )
        """)
        # vec_files: project PARTITION KEY (изоляция на уровне индекса). chunk_id = file_id*STRIDE+idx.
        self.conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_files USING vec0(
                chunk_id INTEGER PRIMARY KEY,
                file_id INTEGER,
                project TEXT PARTITION KEY,
                embedding FLOAT[{DIM}]
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS file_chunks (
                chunk_id INTEGER PRIMARY KEY,
                file_id INTEGER NOT NULL,
                text TEXT NOT NULL
            )
        """)
        # fts_files: rowid = chunk_id → matched CHUNK идентифицируем + O(1) delete по rowid.
        self.conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts_files USING fts5(text)")
        # --- логи: зеркало файлового слоя. logs_indexed = дедуп по log_id (orchestra.db).
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS logs_indexed (
                log_id INTEGER PRIMARY KEY,
                project TEXT NOT NULL
            )
        """)
        self.conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_logs USING vec0(
                chunk_id INTEGER PRIMARY KEY,
                log_id INTEGER,
                kind TEXT,
                project TEXT PARTITION KEY,
                embedding FLOAT[{DIM}]
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS log_chunks (
                chunk_id INTEGER PRIMARY KEY,
                log_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                author TEXT,
                text TEXT NOT NULL
            )
        """)
        self.conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts_logs USING fts5(text)")

    def _embed(self, texts: list[str], is_query: bool) -> list[list[float]]:
        # embedder = module-level singleton, ОБЩИЙ для write- и read-инстансов (thread-safe run()).
        emb = _get_embedder()
        # E5 models need "query: "/"passage: " prefix; bge-m3 doesn't. Explicit flag > name-sniffing.
        if MODEL_PREFIX:
            prefix = "query: " if is_query else "passage: "
            texts = [prefix + t for t in texts]
        return [list(map(float, v)) for v in emb.embed(texts, batch_size=EMBED_BATCH)]

    # ------------------------------------------------------------ файлы

    @staticmethod
    def _sha256(content: str) -> str:
        import hashlib
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _delete_file_rows(self, file_id: int) -> None:
        """Удалить все чанки file_id из vec/fts/file_chunks. Вызывать внутри транзакции."""
        rows = self.conn.execute(
            "SELECT chunk_id FROM file_chunks WHERE file_id=?", (file_id,)
        ).fetchall()
        for r in rows:
            cid = r["chunk_id"]
            self.conn.execute("DELETE FROM vec_files WHERE chunk_id=?", (cid,))
            self.conn.execute("DELETE FROM fts_files WHERE rowid=?", (cid,))
        self.conn.execute("DELETE FROM file_chunks WHERE file_id=?", (file_id,))

    def index_file(self, project: str, rel_path: str, content: str, mtime: float = 0.0) -> int:
        """Индексирует файл проекта. Дедуп по sha256: тот же контент → no-op. Изменился → удаляем
        старые чанки + переиндексируем. Возвращает число проиндексированных чанков (0 = skip)."""
        chunks = _chunk_file(rel_path, content)
        if not chunks:
            return 0
        sha = self._sha256(content)
        existing = self.conn.execute(
            "SELECT file_id, sha256 FROM files WHERE project=? AND path=?", (project, rel_path)
        ).fetchone()
        if existing and existing["sha256"] == sha:
            return 0  # контент не изменился
        vecs = self._embed(chunks, is_query=False)
        self.conn.execute("BEGIN")
        try:
            if existing:
                file_id = existing["file_id"]
                self._delete_file_rows(file_id)
                self.conn.execute("UPDATE files SET sha256=?, mtime=? WHERE file_id=?",
                                  (sha, mtime, file_id))
            else:
                cur = self.conn.execute(
                    "INSERT INTO files(project, path, sha256, mtime) VALUES(?,?,?,?)",
                    (project, rel_path, sha, mtime))
                file_id = int(cur.lastrowid)
            for idx, (chunk, vec) in enumerate(zip(chunks, vecs)):
                cid = file_id * CHUNK_STRIDE + idx
                self.conn.execute(
                    "INSERT INTO vec_files(chunk_id, file_id, project, embedding) VALUES(?,?,?,?)",
                    (cid, file_id, project, _pack(vec)))
                self.conn.execute(
                    "INSERT INTO file_chunks(chunk_id, file_id, text) VALUES(?,?,?)",
                    (cid, file_id, chunk))
                self.conn.execute("INSERT INTO fts_files(rowid, text) VALUES(?,?)", (cid, chunk))
            self.conn.execute("COMMIT")
            return len(chunks)
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    def apply_file_change(self, project: str, deleted: bool, rel_path: str, abs_path: str = "") -> int:
        """Watcher-хук: deleted → delete_file; иначе читаем abs_path и index_file.
        Не-UTF8/пропавший файл → тихо skip (0)."""
        if deleted:
            return 1 if self.delete_file(project, rel_path) else 0
        try:
            content = Path(abs_path).read_text(encoding="utf-8")
            mtime = Path(abs_path).stat().st_mtime
        except (UnicodeDecodeError, OSError):
            return 0
        return self.index_file(project, rel_path, content, mtime)

    def delete_file(self, project: str, rel_path: str) -> bool:
        """Удаляет все чанки файла по (project, path). True если файл был проиндексирован."""
        row = self.conn.execute(
            "SELECT file_id FROM files WHERE project=? AND path=?", (project, rel_path)).fetchone()
        if not row:
            return False
        self.conn.execute("BEGIN")
        try:
            self._delete_file_rows(row["file_id"])
            self.conn.execute("DELETE FROM files WHERE file_id=?", (row["file_id"],))
            self.conn.execute("COMMIT")
            return True
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    # ------------------------------------------------------------ логи

    def _is_log_indexed(self, log_id: int) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM logs_indexed WHERE log_id=?", (log_id,)).fetchone() is not None

    def index_log(self, project: str, log_id: int, kind: str, author: str | None,
                  content: str) -> int:
        """Индексирует один лог (user_msg/agent_msg/text). Дедуп по log_id (logs_indexed).
        Возвращает число чанков (0 = skip: пустой / уже проиндексирован)."""
        if self._is_log_indexed(log_id):
            return 0
        chunks = _chunk(content)
        if not chunks or not content.strip():
            return 0
        vecs = self._embed(chunks, is_query=False)
        self.conn.execute("BEGIN")
        try:
            for idx, (chunk, vec) in enumerate(zip(chunks, vecs)):
                cid = log_id * CHUNK_STRIDE + idx
                self.conn.execute(
                    "INSERT INTO vec_logs(chunk_id, log_id, kind, project, embedding) VALUES(?,?,?,?,?)",
                    (cid, log_id, kind, project, _pack(vec)))
                self.conn.execute(
                    "INSERT INTO log_chunks(chunk_id, log_id, kind, author, text) VALUES(?,?,?,?,?)",
                    (cid, log_id, kind, author, chunk))
                self.conn.execute("INSERT INTO fts_logs(rowid, text) VALUES(?,?)", (cid, chunk))
            self.conn.execute("INSERT INTO logs_indexed(log_id, project) VALUES(?,?)", (log_id, project))
            self.conn.execute("COMMIT")
            return len(chunks)
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    @staticmethod
    def _log_is_signal(kind: str, content: str) -> bool:
        """Length-фильтр по kind (plan §0): agent_msg — без порога (шума 1.2%), остальные — MIN_LOG_LEN."""
        if kind == "agent_msg":
            return bool(content and content.strip())
        return len(content or "") >= MIN_LOG_LEN

    def backfill_logs(self, project: str, orchestra_db: Path, batch_size: int = 500) -> int:
        """Индексирует логи проекта из orchestra.db (user_message/text). ATTACH read-only,
        джойн logs+sessions по scope=project. type/kind/length фильтр. Дедуп по logs_indexed.
        Возвращает число проиндексированных логов."""
        import sqlite3
        try:
            self.conn.execute(f"ATTACH DATABASE 'file:{orchestra_db}?mode=ro' AS orch")
        except sqlite3.OperationalError:
            pass  # уже приаттачена
        try:
            type_ph = ",".join("?" * len(LOG_TYPES))
            rows = self.conn.execute(f"""
                SELECT l.id, l.type, l.content
                FROM orch.logs l JOIN orch.sessions s ON l.session_id = s.id
                WHERE s.scope = ? AND l.type IN ({type_ph})
                  AND l.id NOT IN (SELECT log_id FROM logs_indexed)
                ORDER BY l.id
            """, (project, *LOG_TYPES)).fetchall()
        finally:
            self.conn.execute("DETACH DATABASE orch")
        count = 0
        for r in rows:
            kind, author = _classify_log(r["type"], r["content"])
            if not self._log_is_signal(kind, r["content"]):
                # помечаем как обработанный, чтобы не пересматривать каждый backfill
                self.conn.execute("INSERT OR IGNORE INTO logs_indexed(log_id, project) VALUES(?,?)",
                                  (r["id"], project))
                continue
            if self.index_log(project, r["id"], kind, author, r["content"]):
                count += 1
        if count:
            logger.info(f"RAG backfill_logs[{project}] indexed {count} logs")
        return count

    # ------------------------------------------------------------ search

    @staticmethod
    def _expand_query(query: str) -> str | None:
        """prefix-expansion для морфологии: 'ссора Катей' → '\"ссора\"* OR \"Катей\"*'.
        Ловит суффиксальные словоформы. Слова <3 символов отбрасываем."""
        words = [w for w in re.findall(r"\w+", query) if len(w) >= 3]
        if not words:
            return None
        return " OR ".join(f'"{w}"*' for w in words)

    def _vec_search_files(self, project: str, query_vec: list[float], pool: int,
                          cross: bool) -> list[int]:
        if cross:
            sql = "SELECT chunk_id FROM vec_files WHERE embedding MATCH ? ORDER BY distance LIMIT ?"
            params: list = [_pack(query_vec), pool * 3]
        else:
            sql = ("SELECT chunk_id FROM vec_files WHERE project=? AND embedding MATCH ? "
                   "ORDER BY distance LIMIT ?")
            params = [project, _pack(query_vec), pool * 3]
        return [r["chunk_id"] for r in self.conn.execute(sql, params).fetchall()][:pool]

    def _fts_search_files(self, project: str, query: str, pool: int, cross: bool) -> list[int]:
        # fts не знает project → фильтруем join'ом на file_chunks→files.
        proj_sql = "" if cross else "AND f.project=? "
        sql = (f"SELECT ft.rowid AS chunk_id FROM fts_files ft "
               f"JOIN file_chunks fc ON fc.chunk_id=ft.rowid "
               f"JOIN files f ON f.file_id=fc.file_id "
               f"WHERE fts_files MATCH ? {proj_sql}ORDER BY rank LIMIT ?")

        def _params(q):
            p: list = [q]
            if not cross:
                p.append(project)
            p.append(pool * 3)
            return p
        match = self._expand_query(query) or ('"' + query.replace('"', '""') + '"')
        try:
            rows = self.conn.execute(sql, _params(match)).fetchall()
        except Exception:
            safe = '"' + query.replace('"', '""') + '"'
            rows = self.conn.execute(sql, _params(safe)).fetchall()
        return [r["chunk_id"] for r in rows][:pool]

    def _vec_search_logs(self, project: str, query_vec: list[float], pool: int,
                         cross: bool, kinds: tuple | None) -> list[int]:
        conds, params = ["embedding MATCH ?"], [_pack(query_vec)]
        if not cross:
            conds.append("project=?")
            params.append(project)
        if kinds:
            conds.append(f"kind IN ({','.join('?' * len(kinds))})")
            params.extend(kinds)
        sql = f"SELECT chunk_id FROM vec_logs WHERE {' AND '.join(conds)} ORDER BY distance LIMIT ?"
        params.append(pool * 3)
        return [r["chunk_id"] for r in self.conn.execute(sql, params).fetchall()][:pool]

    def _fts_search_logs(self, project: str, query: str, pool: int, cross: bool,
                         kinds: tuple | None) -> list[int]:
        # fts не знает project/kind → join на log_chunks (kind) + logs_indexed (project).
        extra: list = []
        proj_sql = ""
        if not cross:
            proj_sql = "AND li.project=? "
            extra.append(project)
        kind_sql = ""
        if kinds:
            kind_sql = f"AND lc.kind IN ({','.join('?' * len(kinds))}) "
            extra.extend(kinds)
        sql = (f"SELECT ft.rowid AS chunk_id FROM fts_logs ft "
               f"JOIN log_chunks lc ON lc.chunk_id=ft.rowid "
               f"JOIN logs_indexed li ON li.log_id=lc.log_id "
               f"WHERE fts_logs MATCH ? {proj_sql}{kind_sql}ORDER BY rank LIMIT ?")

        def _params(q):
            return [q, *extra, pool * 3]
        match = self._expand_query(query) or ('"' + query.replace('"', '""') + '"')
        try:
            rows = self.conn.execute(sql, _params(match)).fetchall()
        except Exception:
            safe = '"' + query.replace('"', '""') + '"'
            rows = self.conn.execute(sql, _params(safe)).fetchall()
        return [r["chunk_id"] for r in rows][:pool]

    @staticmethod
    def _rrf(*ranked_lists: list, k: int = RRF_K) -> list:
        """RRF над произвольным числом ранжированных списков. Ключи — любые hashable
        (namespaced ('file',id)/('log',id) → файл и лог с равными int не схлопнутся)."""
        scores: dict = {}
        for lst in ranked_lists:
            for rank, key in enumerate(lst):
                scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
        return sorted(scores, key=lambda m: scores[m], reverse=True)

    def search(self, project: str, query: str, limit: int = 5, cross_project: bool = False,
               kinds: tuple | None = None) -> list[dict]:
        """Hybrid search (vec + fts, RRF fusion) по файлам И логам проекта. cross_project=True →
        по всем проектам (явный опт-ин, снимает изоляцию). kinds → фильтр логов по kind."""
        query = (query or "").strip()
        if not query:
            return []
        pool = max(limit * POOL_MULT, limit)
        qvec = self._embed([query], is_query=True)[0]
        f_vec = [("file", c) for c in self._vec_search_files(project, qvec, pool, cross_project)]
        f_fts = [("file", c) for c in self._fts_search_files(project, query, pool, cross_project)]
        l_vec = [("log", c) for c in self._vec_search_logs(project, qvec, pool, cross_project, kinds)]
        l_fts = [("log", c) for c in self._fts_search_logs(project, query, pool, cross_project, kinds)]
        ranked = self._rrf(f_vec, f_fts, l_vec, l_fts)
        if not ranked:
            return []

        file_cids = [key[1] for key in ranked if key[0] == "file"]
        log_cids = [key[1] for key in ranked if key[0] == "log"]
        file_rows: dict = {}
        if file_cids:
            ph = ",".join("?" * len(file_cids))
            sql = (f"SELECT fc.chunk_id, fc.text AS content, f.path, f.project "
                   f"FROM file_chunks fc JOIN files f ON f.file_id=fc.file_id "
                   f"WHERE fc.chunk_id IN ({ph})")
            file_rows = {r["chunk_id"]: {"source": "file", "project": r["project"],
                                         "path": r["path"], "content": r["content"]}
                         for r in self.conn.execute(sql, list(file_cids)).fetchall()}
        log_rows: dict = {}
        if log_cids:
            ph = ",".join("?" * len(log_cids))
            sql = (f"SELECT lc.chunk_id, lc.text AS content, lc.kind, lc.author, lc.log_id, "
                   f"li.project FROM log_chunks lc JOIN logs_indexed li ON li.log_id=lc.log_id "
                   f"WHERE lc.chunk_id IN ({ph})")
            log_rows = {r["chunk_id"]: {"source": "log", "project": r["project"],
                                        "kind": r["kind"], "author": r["author"],
                                        "log_id": r["log_id"], "content": r["content"]}
                        for r in self.conn.execute(sql, list(log_cids)).fetchall()}
        out = []
        for kind, key in ranked:
            row = file_rows.get(key) if kind == "file" else log_rows.get(key)
            if row:
                out.append(row)
                if len(out) >= limit:
                    break
        return out

    def _walk_files(self, root: Path) -> list[Path]:
        """Все .md под root, пропуская EXCLUDED_DIRS и EXCLUDED_FILE_RE. Абсолютные пути."""
        import os
        found: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
            for fn in filenames:
                if Path(fn).suffix.lower() in FILE_EXTENSIONS and not EXCLUDED_FILE_RE.search(fn):
                    found.append(Path(dirpath) / fn)
        return found

    def backfill_files(self, project: str, root: Path) -> int:
        """Индексирует все .md проекта. Дедуп по sha256 → повторный запуск дёшев. Не-UTF8 → skip.
        Prune: файлы из `files` которых нет на диске → удаляем. Возвращает число (ре)индексаций."""
        root = root.resolve()
        if not root.is_dir():
            logger.warning(f"RAG backfill_files: dir not found: {root}")
            return 0
        disk_paths = self._walk_files(root)
        seen_rel: set[str] = set()
        count = 0
        for abs_path in disk_paths:
            rel = str(abs_path.relative_to(root))
            seen_rel.add(rel)
            try:
                content = abs_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                logger.warning(f"RAG backfill_files: skip non-UTF8 {rel}")
                continue
            except OSError as e:
                logger.warning(f"RAG backfill_files: skip {rel}: {e}")
                continue
            try:
                mtime = abs_path.stat().st_mtime
            except OSError:
                mtime = 0.0
            if self.index_file(project, rel, content, mtime):
                count += 1
        # prune: индексированные пути проекта, которых больше нет на диске
        indexed = [r["path"] for r in self.conn.execute(
            "SELECT path FROM files WHERE project=?", (project,)).fetchall()]
        for rel in indexed:
            if rel not in seen_rel:
                self.delete_file(project, rel)
                logger.info(f"RAG backfill_files: pruned stale {rel}")
        if count:
            logger.info(f"RAG backfill_files[{project}] indexed/updated {count} files")
        return count


# Два инстанса + два executor'а: write (index/backfill, RW conn) и read (search, RO conn).
# WAL → read не блокируется write. search эмбедит запрос в СВОЁМ потоке параллельно backfill'у.
_db: RagMemory | None = None        # write instance (RW conn)
_db_ro: RagMemory | None = None     # read instance (RO conn)
_executor = None                    # write ThreadPoolExecutor(max_workers=1)
_read_executor = None               # read ThreadPoolExecutor(max_workers=1)
_READ_METHODS = {"search"}          # идут в read-executor (RO conn, не ждут backfill)
_DB_PATH = DB_PATH


def set_executor(ex, read_ex=None, db_path: Path | None = None) -> None:
    global _executor, _read_executor, _DB_PATH
    _executor = ex
    _read_executor = read_ex if read_ex is not None else ex  # fallback: один executor (тесты)
    if db_path is not None:
        _DB_PATH = db_path


def get_rag() -> RagMemory:
    """Write-инстанс (RW conn). ВЫЗЫВАТЬ ТОЛЬКО внутри write-executor-потока."""
    global _db
    if _db is None:
        _db = RagMemory(path=_DB_PATH)
    return _db


def get_rag_ro() -> RagMemory:
    """Read-инстанс (RO conn к той же WAL-БД). ВЫЗЫВАТЬ ТОЛЬКО внутри read-executor-потока."""
    global _db_ro
    if _db_ro is None:
        _db_ro = RagMemory(path=_DB_PATH, readonly=True)
    return _db_ro


async def run(loop, method: str, *args):
    """Выполнить RagMemory.<method>(*args) в нужном executor-потоке. search → read-executor
    (RO conn, конкурентно с backfill), остальное → write-executor. get_rag* вызывается ВНУТРИ
    executor — иначе коннект привяжется к loop-потоку (SQLite check_same_thread)."""
    if method in _READ_METHODS:
        def _call_ro():
            return getattr(get_rag_ro(), method)(*args)
        return await loop.run_in_executor(_read_executor, _call_ro)
    def _call():
        return getattr(get_rag(), method)(*args)
    return await loop.run_in_executor(_executor, _call)
