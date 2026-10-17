# Context for item-43

## Diff reviewed (-U20, capped at 1500 lines)

diff --git a/app/rag.py b/app/rag.py
index 3bb17a149..5c8f2d54f 100644
--- a/app/rag.py
+++ b/app/rag.py
@@ -20,40 +20,43 @@ from pathlib import Path
 
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
+# СМЕНА МОДЕЛИ ЭМБЕДДИНГА — тоже повод бампнуть: `index_file` переиспользует вектора
+# неизменившихся чанков (#73), поэтому без дропа старые вектора останутся в индексе навсегда
+# и будут соседствовать с новыми в одном поиске.
 SCHEMA_VERSION = 1
 POOL_MULT = 4  # candidate pool = limit * POOL_MULT перед RRF
 
 # Chunking длинных текстов. В символах (~4 символа/токен рус.), без tiktoken.
 CHUNK_CHAR_LIMIT = 1200   # ~300 токенов — выше этого режем
 CHUNK_SIZE = 800          # ~200 токенов на кусок
 CHUNK_OVERLAP = 200       # ~50 токенов перекрытие
 CHUNK_STRIDE = 1000       # макс чанков на источник (chunk_id = source_id*STRIDE + idx)
 EMBED_BATCH = int(os.getenv("RAG_EMBED_BATCH", "64"))  # kesha benchmark: 64 optimal (98ms/chunk)
 RAG_ONNX_THREADS = int(os.getenv("RAG_ONNX_THREADS", "2"))  # cap ONNX threads (0=all cores=490% CPU)
 RAG_NICE = int(os.getenv("RAG_NICE", "10"))  # os.nice() on backfill thread
 
 # Файловая индексация. Только markdown-проза: .md.
 # xml/csv/json/html = машинные данные/логи → мусор в retrieval (kesha-замер).
 FILE_EXTENSIONS = {".md"}
 EXCLUDED_DIRS = {".git", ".claude", ".gemini", ".kiro", ".github", ".serena",
                  ".claude-plugin", "node_modules", "__pycache__", ".venv", "worktrees"}
 # codex-review-*.md = дебаты до 406KB, шум > сигнал (plan §0) → блэклист по имени.
 EXCLUDED_FILE_RE = re.compile(r"codex-review.*\.md$")
 
@@ -403,70 +406,92 @@ class RagMemory:
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
 
+    def _reusable_vectors(self, file_id: int) -> dict[str, bytes]:
+        """{текст чанка → готовый вектор} по прошлой версии файла.
+
+        Ключ — ТЕКСТ, а не позиция: `CHANGELOG.md` растёт дописыванием блока СВЕРХУ, у чанков
+        меняется индекс, а содержимое остаётся. Замер #73 по пяти его последним версиям:
+        новых текстов 0.6–11.2 % при 352 чанках, то есть 89–99 % эмбеддингов считались заново
+        без единого изменения в тексте (352 × 2.2 с ≈ 775 с на файл при бюджете прохода 300 с).
+        """
+        rows = self.conn.execute(
+            "SELECT c.text, v.embedding FROM file_chunks c JOIN vec_files v USING(chunk_id) "
+            "WHERE c.file_id=?", (file_id,)).fetchall()
+        return {r["text"]: r["embedding"] for r in rows}
+
     def index_file(self, project: str, rel_path: str, content: str, mtime: float = 0.0) -> int:
         """Индексирует файл проекта. Дедуп по sha256: тот же контент → no-op. Изменился → удаляем
-        старые чанки + переиндексируем. Возвращает число проиндексированных чанков (0 = skip)."""
+        старые чанки + переиндексируем, считая эмбеддинги ТОЛЬКО для новых по тексту чанков.
+        Возвращает число проиндексированных чанков (0 = skip)."""
         chunks = _chunk_file(rel_path, content)
         if not chunks:
             return 0
         sha = self._sha256(content)
         existing = self.conn.execute(
             "SELECT file_id, sha256 FROM files WHERE project=? AND path=?", (project, rel_path)
         ).fetchone()
         if existing and existing["sha256"] == sha:
             return 0  # контент не изменился
-        vecs = self._embed(chunks, is_query=False)
+        reused = self._reusable_vectors(existing["file_id"]) if existing else {}
+        fresh = [c for c in chunks if c not in reused]
+        # Порядок сохраняется: `fresh` идёт в том же порядке, что и chunks, поэтому вектора
+        # разбираются по одному ровно для тех чанков, которых не было в прошлой версии.
+        new_vecs = iter(self._embed(fresh, is_query=False) if fresh else ())
+        blobs = [reused[c] if c in reused else _pack(next(new_vecs)) for c in chunks]
+        if len(fresh) < len(chunks):
+            logger.info(f"RAG index_file[{rel_path}] переиспользовано "
+                        f"{len(chunks) - len(fresh)}/{len(chunks)} чанков")
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
-            for idx, (chunk, vec) in enumerate(zip(chunks, vecs)):
+            for idx, (chunk, blob) in enumerate(zip(chunks, blobs)):
                 cid = file_id * CHUNK_STRIDE + idx
                 self.conn.execute(
                     "INSERT INTO vec_files(chunk_id, file_id, project, embedding) VALUES(?,?,?,?)",
-                    (cid, file_id, project, _pack(vec)))
+                    (cid, file_id, project, blob))
                 self.conn.execute(
                     "INSERT INTO file_chunks(chunk_id, file_id, text) VALUES(?,?,?)",
                     (cid, file_id, chunk))
                 self.conn.execute("INSERT INTO fts_files(rowid, text) VALUES(?,?)", (cid, chunk))
             self.conn.execute("COMMIT")
             return len(chunks)
         except Exception:
             self.conn.execute("ROLLBACK")
             raise
 
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
diff --git a/docs/tasks/73/measure_reuse.py b/docs/tasks/73/measure_reuse.py
new file mode 100644
index 000000000..5e108607d
--- /dev/null
+++ b/docs/tasks/73/measure_reuse.py
@@ -0,0 +1,66 @@
+"""#73 — цена переиндексации CHANGELOG.md до и после переиспользования эмбеддингов.
+
+Данные РЕАЛЬНЫЕ: две соседние версии файла из git. Синтетика тут дала бы неверную цену —
+эмбеддинг стоит пропорционально тексту, а повторяющийся текст ещё и меняет границы чанков.
+
+Плечи считаются от ОДНОГО и того же состояния индекса: v1 индексируется один раз, база
+копируется, дальше каждое плечо доиндексирует v2 на своей копии.
+
+Запуск: /home/kesha/orchestra/.venv/bin/python docs/tasks/73/measure_reuse.py [rev1] [rev2]
+"""
+import shutil
+import subprocess
+import sys
+import time
+from pathlib import Path
+
+sys.path.insert(0, "/home/kesha/orchestra/worktrees/home-kesha-orchestra/back")
+
+from app import rag  # noqa: E402
+
+REPO = "/home/kesha/orchestra"
+BASE = Path("/tmp/back73_base.db")
+ARM = Path("/tmp/back73_arm.db")
+
+
+def version(rev: str) -> str:
+    return subprocess.run(["git", "-C", REPO, "show", f"{rev}:CHANGELOG.md"],
+                          capture_output=True, text=True).stdout
+
+
+def fresh(path: Path) -> None:
+    for suffix in ("", "-wal", "-shm"):
+        p = Path(str(path) + suffix)
+        if p.exists():
+            p.unlink()
+
+
+def main() -> None:
+    rev1 = sys.argv[1] if len(sys.argv) > 1 else "9122839"
+    rev2 = sys.argv[2] if len(sys.argv) > 2 else "114167a"
+    v1, v2 = version(rev1), version(rev2)
+    c1, c2 = rag._chunk_file("CHANGELOG.md", v1), rag._chunk_file("CHANGELOG.md", v2)
+    new_texts = len([c for c in c2 if c not in set(c1)])
+    print(f"{rev1} → {rev2}: чанков {len(c1)} → {len(c2)}, новых по тексту {new_texts}", flush=True)
+
+    fresh(BASE)
+    mem = rag.RagMemory(path=BASE)
+    started = time.monotonic()
+    mem.index_file(REPO, "CHANGELOG.md", v1)
+    print(f"подготовка (индексация {rev1} с нуля): {time.monotonic() - started:.0f} с", flush=True)
+    mem.conn.close()
+
+    for label, reuse in (("после (переиспользование)", True), ("до (как было)", False)):
+        fresh(ARM)
+        shutil.copy(BASE, ARM)
+        arm = rag.RagMemory(path=ARM)
+        if not reuse:
+            arm._reusable_vectors = lambda _file_id: {}
+        started = time.monotonic()
+        n = arm.index_file(REPO, "CHANGELOG.md", v2)
+        print(f"{label}: {time.monotonic() - started:.0f} с на {n} чанков", flush=True)
+        arm.conn.close()
+
+
+if __name__ == "__main__":
+    main()
diff --git a/docs/tasks/73/report.md b/docs/tasks/73/report.md
new file mode 100644
index 000000000..ce5824296
--- /dev/null
+++ b/docs/tasks/73/report.md
@@ -0,0 +1,71 @@
+# #73 — переиндексация CHANGELOG подешевела с 1190 до 21 секунды: эмбеддинги неизменившихся чанков переиспользуются
+
+Постановка предлагала выбор из двух вариантов; замер (`research.md`) показал третий, который
+дешевле обоих и ничего не теряет. Реализован он.
+
+## Замер до/после — реальные версии файла, не синтетика
+
+Две соседние версии `CHANGELOG.md` из git, оба плеча стартуют от ОДНОГО состояния индекса:
+v1 индексируется один раз, база копируется, каждое плечо доиндексирует v2 на своей копии
+(`docs/tasks/73/measure_reuse.py`).
+
+```
+9122839 → 114167a: чанков 345 → 352, новых по тексту 8
+
+подготовка (индексация 9122839 с нуля): 1169 с
+до (как было):                          1190 с на 352 чанка
+после (переиспользование):                21 с на 352 чанка
+```
+
+**57×.** 8 новых чанков × 2.2 с ≈ 18 с плюс накладные — сходится с ценой чанка из `research.md`.
+Бюджет прохода — 300 с, то есть файл из «съедает проход целиком и не помещается» стал стоить
+7 % прохода.
+
+Синтетику для этого замера брать было нельзя: стоимость эмбеддинга пропорциональна тексту, а
+повторяющийся текст ещё и меняет границы чанков — цена вышла бы неверной дважды.
+
+## Как сделано
+
+`index_file` перед эмбеддингом поднимает из прошлой версии файла пару «текст чанка → готовый
+вектор» (`_reusable_vectors`: `file_chunks.text` JOIN `vec_files.embedding` по `chunk_id`),
+считает эмбеддинги ТОЛЬКО для новых по тексту чанков, остальные перекладывает как есть.
+
+- **Ключ — текст чанка, а не позиция.** `CHANGELOG.md` растёт дописыванием блока СВЕРХУ: у
+  чанков меняется индекс, а содержимое остаётся. Хэш не понадобился — сравнение по самому
+  тексту, ложных совпадений не бывает по определению.
+- **Схема не менялась, транзакция осталась одна.** Ни новых колонок, ни частичных коммитов,
+  ни состояния «файл проиндексирован наполовину» — то есть это именно C, а не половина A.
+- Порядок сохраняется: список новых чанков идёт в порядке `chunks`, вектора разбираются по
+  одному ровно для тех, которых не было в прошлой версии.
+- Строка в журнале `переиспользовано N/M чанков` — иначе эффект виден только по времени прохода.
+
+## Тесты
+
+`test_reindex_reuses_embeddings_of_unchanged_chunks` — дописывание блока сверху приводит к
+ОДНОМУ вызову эмбеддера на один новый чанк (перехват `_embed`, проверяется и число вызовов, и
+что в него попал именно новый текст). `test_reused_vectors_are_the_same_bytes` — переложенный
+вектор побайтово тот же, иначе поиск поедет незаметно.
+
+Мутация: `reused = {}` (переиспользование выключено) — **оба теста краснеют**.
+
+Прогон: `/home/kesha/orchestra/.venv/bin/python -m pytest tests/test_rag.py tests/test_rag_service.py`
+→ 64 passed. В worktree воркера тот же прогон скипнет реальный слой RAG и скажет об этом громко (#63).
+
+**Грабля в самих тестах, стоившая цикла:** первая версия использовала короткие секции, и тесты
+падали. Причина не в коде, а в чанкере: секция короче `MD_MIN_MERGE = 250` символов сливается с
+соседней, поэтому дописывание меняет ТЕКСТ соседнего чанка, а не только его позицию.
+Переиспользование на таких файлах не работает и работать не должно. На реальном `CHANGELOG.md`
+секции крупные — оттуда и 0.6–11.2 % новых текстов вместо 100 %.
+
+## Границы, оставленные сознательно
+
+- **Первая индексация нового большого файла по-прежнему дорогая**: 1169 с на 187 КБ с нуля,
+  переиспользовать нечего. Случай разовый на файл и редкий (1 файл из 490 дороже 100 чанков).
+  Вариант A (дедлайн внутрь чанк-цикла с возобновляемостью) вернём страховкой, если этот
+  редкий случай начнёт мешать.
+- **Файлы с короткими секциями** (< 250 символов) переиспользование не получают — см. выше.
+  Это не дефект: у них и стоимость переиндексации маленькая.
+- **Смена модели эмбеддинга теперь обязана бампать `SCHEMA_VERSION`.** Раньше вектора старой
+  модели вымывались по мере изменения файлов; теперь неизменившийся чанк хранит свой вектор
+  сколько угодно долго, и без дропа таблиц в одном поиске соседствовали бы вектора двух моделей.
+  Записано комментарием рядом с `SCHEMA_VERSION`.
diff --git a/docs/tasks/73/research.md b/docs/tasks/73/research.md
new file mode 100644
index 000000000..26ff7f88a
--- /dev/null
+++ b/docs/tasks/73/research.md
@@ -0,0 +1,100 @@
+# #73 — стоимость одного элемента: сравнение вариантов
+
+Задача ставилась как выбор из двух: дедлайн внутрь чанк-цикла (правильное) против потолка на
+размер с громким пропуском (дешёвое). Замер показал третий вариант, который дешевле обоих и
+ничего не теряет. Ниже цифры, на которых это видно.
+
+## 1. Что мы вообще чиним — размер задачи
+
+Корпус после фикса `.gitignore` (#63): **490 файлов, 8833 чанка**, медиана 12 чанков на файл,
+90-й перцентиль — 38.
+
+```
+352 чанка  187 КБ  CHANGELOG.md          ← в 4.2 раза больше следующего
+ 83 чанка   43 КБ  docs/archive/sessions/2026-07.md
+ 73 чанка   38 КБ  docs/tasks/98-grok-runtime-audit/research.md
+ 70 чанков  41 КБ  docs/tasks/116/research.md
+```
+
+| порог | файлов | доля корпуса | доля чанков |
+|---|---|---|---|
+| > 50 чанков | 17 | 3.5 % | 15 % |
+| > 100 чанков | **1** | 0.2 % | 4 % |
+
+Цена чанка на этой машине сейчас (bge-m3 int8, `RAG_ONNX_THREADS=2`, живой сервер рядом):
+**2.2 с/чанк** при батчах 8 и 24 (batch=1 даёт 7.95 с — прогрев модели, не показатель).
+Батчинг по-прежнему ничего не даёт, как и в #16.
+
+Отсюда **CHANGELOG.md = 352 × 2.2 ≈ 775 с ≈ 13 минут** на одну переиндексацию при бюджете
+прохода 300 с. Второй по величине файл — 83 чанка ≈ 180 с — в бюджет укладывается.
+**Проблема ровно одна и имеет имя: `CHANGELOG.md`.**
+
+## 2. Ключевое обстоятельство: он меняется каждый мерж
+
+После #52 changelog собирается скриптом и растёт при каждой задаче. Значит его sha меняется
+почти каждый мерж, а мерж — это и есть триггер прогона. То есть **самый дорогой файл корпуса
+одновременно самый часто меняющийся**: он готов съедать 775 с каждого прохода при бюджете 300 с,
+вытесняя все остальные 489 файлов.
+
+## 3. Сколько в нём на самом деле меняется — замер по истории
+
+Взял пять последних коммитов `CHANGELOG.md`, порезал каждую версию тем же чанкером и сравнил
+по ТЕКСТУ чанка:
+
+```
+b089aea: чанков 301 | новых по тексту 10 (3.3 %)
+691df4d: чанков 338 | новых по тексту 38 (11.2 %)
+9122839: чанков 345 | новых по тексту  7 (2.0 %)
+b864458: чанков 351 | новых по тексту  6 (1.7 %)
+114167a: чанков 352 | новых по тексту  2 (0.6 %)
+```
+
+**Меняется 0.6–11.2 % чанков, остальные 89–99 % — тот же текст.** Скрипт дописывает блок
+СВЕРХУ, но чанкер heading-aware, поэтому границы секций не плывут: у чанков меняется только
+позиция, а не содержимое. Мы каждый раз считаем 352 эмбеддинга там, где новых текстов 2–38.
+
+## 4. Три варианта и их цена
+
+### A. Дедлайн внутрь чанк-цикла (то, что считалось правильным)
+
+Требует **возобновляемости**: `index_file` сейчас эмбеддит файл целиком и пишет одной
+транзакцией, sha ставится по завершении. Оборвать на середине можно только двумя способами —
+либо не писать sha (тогда следующий проход начнёт файл С НУЛЯ, и файл дороже бюджета не
+проиндексируется НИКОГДА), либо хранить прогресс по чанкам: новая колонка, частичный коммит,
+поиск по недоиндексированному файлу, новые состояния при обрыве.
+
+Цена: ~60+ строк в центральном пути записи, новое состояние, новые режимы отказа.
+**И этого мало**: даже с возобновляемостью CHANGELOG требует 775 с = 3 прохода, а меняется
+каждый мерж, то есть каждый проход. Он не догонит сам себя — вариант A в реальном случае
+**не сходится**.
+
+### B. Потолок на размер + громкий пропуск (дешёвое)
+
+Цена: ~10 строк. Но потолок в 100 чанков выкидывает ровно один файл — `CHANGELOG.md`, историю
+проекта; потолок в 50 — уже 17 файлов и 15 % корпуса, и это исследовательские отчёты, то есть
+ровно то, ради чего память заведена. Громкий пропуск честен, но он сообщает агенту, что нужного
+документа в памяти нет, а не решает задачу.
+
+### C. Переиспользовать эмбеддинги неизменившихся чанков ← рекомендую
+
+Текст чанка уже лежит в `file_chunks.text`, вектор — в `vec_files.embedding`, оба по `chunk_id`.
+Значит при переиндексации можно поднять пару «текст → вектор», сопоставить с новым списком
+чанков и посчитать эмбеддинги ТОЛЬКО для новых текстов; неизменившиеся переложить как есть.
+
+Цена: ~25 строк в `index_file`, **без изменения схемы**, без нового состояния, без частичных
+коммитов — транзакция остаётся одна, файл по-прежнему индексируется целиком.
+
+Эффект по замеру §3: **775 с → 4–84 с** (2–38 новых чанков × 2.2 с), медиана ≈ 13 с.
+Помогает не только changelog: отчёты и `docs/archive/**` тоже растут дописыванием.
+
+### Чего вариант C НЕ чинит
+
+Первую индексацию по-настоящему нового большого файла: 775 с так и останутся, переиспользовать
+нечего. Случай редкий (1 файл из 490) и разовый на файл, перебор бюджета ограничен размером
+самого файла. Если и это захотим закрыть — тогда A, но уже как страховка от редкого случая, а
+не как основное решение, и цена его к тому моменту будет оправдана.
+
+## 5. Что предлагаю взять
+
+**C сейчас, A — не брать.** B не брать вовсе: он экономит на том самом документе, ради поиска
+по которому память и существует.
diff --git a/docs/workers/back.md b/docs/workers/back.md
index 84425aa84..0261c72f4 100644
--- a/docs/workers/back.md
+++ b/docs/workers/back.md
@@ -80,40 +80,46 @@
   дедлок в проде. **Сформулировал это правило — и следующим же коммитом в него попал:**
   `blocked_backfill(_scope)` в `tests/test_api.py` остался стоять и блокировал всем полный
   прогон сутки. Правило работает только как ШАГ, а не как знание: сменил сигнатуру →
   до коммита `grep -rn "def fake_\|def blocked_\|def stub_" tests/` **и прогнать те файлы,
   которые её мокают** (мой прогон #28 их не включал — оттуда и дыра).
 
 - **«Никто не зовёт» ≠ «никому не нужен».** Перед удалением роута смотри не только КТО ЕГО
   ЗОВЁТ, но и КТО ЧИТАЕТ ЕГО ДАННЫЕ и не рекламирует ли его строка в ответе соседнего роута.
   `GET /api/report_bug` вызывающего кода не имел вовсе — и был единственным читателем стора
   `~/.local/state/orchestra/bug-inbox/records/` (0600, вне git — так задумано), куда `POST`
   кладёт каждый репорт отдельным файлом. **`BUGS.md` репозитория с 01.08 не пополняется:**
   всё новое лежит там, 7 репортов на момент проверки. Плюс `POST` возвращает агенту дословно
   `Read: /api/report_bug` (`mcp_stdio.py:1418`) — удаление сделало бы из этого ссылку на 404.
 
 - **CHANGELOG.md руками БОЛЬШЕ НЕ правится (#52).** Источник — ПЕРВАЯ СТРОКА
   `docs/tasks/<id>/report.md`, она и есть запись changelog: формат `# #<id> — <текст>`, сборка
   `uv run python scripts/build-changelog.py [--write --version vX.Y.Z]`. Проверить, как твоя
   строка попадёт в файл, — сухим прогоном того же скрипта. Я по привычке начал писать блок
   руками и поймал себя только на конфликте: механизм сменился под задачей.
 
+- **Тесты чанкера на КОРОТКИХ секциях врут.** Секция короче `MD_MIN_MERGE = 250` символов
+  сливается с соседней, поэтому дописывание меняет ТЕКСТ соседнего чанка, а не только его
+  позицию — мой тест на переиспользование эмбеддингов (#73) падал именно на этом, а не на коде.
+  Для чанкерных тестов секции строить длиннее 250 символов, иначе проверяешь слияние, а не то,
+  что хотел. Цена элемента меряется в ЧАНКАХ, не в килобайтах: 2.2 с/чанк, батчинг не помогает.
+
 - **Долг индексации RAG сперва РАЗЛОЖИ по каталогам, потом ускоряй.** В #63 94 % долга (459 из
   490) оказались `data/bench138/` — чужим бенчмарк-корпусом под `.gitignore`, который обходчик
   не пропускал. Ускорять индексацию мусора можно бесконечно. Разложение — один проход os.walk
   + `Counter(rel.split("/")[0])`, минута работы; оно же опровергло мой собственный вывод в #44
   про «корпус удвоил мерж контура ноутбука».
 
 - **RAG-бэкфилл не логирует прогресс — только `start` и финальную строку.** Дедлайн
   `_PASS_BUDGET_SECONDS=300` проверяется МЕЖДУ срезами (`rag_service.py:162-171`), а срез =
   5 файлов + 100 логов ≈ до 290 с → до ~10 минут тишины в journald при живом прогоне. Пустой
   `journalctl | grep RAG` чаще значит «бэкфилл никто не запускал» (он идёт только по мержу или
   `/api/memory/reindex`), а не «логи сломаны». Жив ли прогон — смотреть
   `py-spy dump --pid <pid> | grep -A6 rag-w_0` (видно и слой: `backfill_files` против логов);
   `COUNT(*) FROM logs_indexed` растёт СТУПЕНЯМИ по срезу, ноль за минуту — ещё не «встало».
 
 - **Трафик считать ПО ПРОВОДУ, а не по `len(body)`:** дашборд стоит за nginx, и он жмёт JSON.
   `/api/models` — 4732 B тела и **747 B** на проводе (+162 B заголовков), коэффициент 6.3.
   Проверка одной командой: `curl -s -o /dev/null -D - --compressed -H "Authorization: Bearer
   $INTERNAL_TOKEN" https://orchestra.seedon.ru/<путь> -w '%{size_download}\n'`. Постановка
   задачи #37 исходила из несжатой цифры и завышала экономию в 6 раз.
 
diff --git a/tests/test_rag.py b/tests/test_rag.py
index aa4102302..d6979043b 100644
--- a/tests/test_rag.py
+++ b/tests/test_rag.py
@@ -643,20 +643,67 @@ def test_backfill_skips_git_ignored_files(mem, tmp_path):
 
     assert mem.backfill_files("/proj/a", kb) == 1
     paths = {r[0] for r in mem.conn.execute("SELECT path FROM files").fetchall()}
     assert paths == {"README.md"}
 
 
 @needs_model
 def test_walk_indexes_everything_when_git_is_unavailable(mem, tmp_path, monkeypatch):
     """Сбой git не имеет права молча сужать корпус: пустая память хуже шумной."""
     kb = tmp_path / "notrepo"          # не git-репозиторий вовсе → rc=128
     kb.mkdir()
     (kb / "a.md").write_text("# A\n\nдокумент один достаточной длины", encoding="utf-8")
     (kb / "b.md").write_text("# B\n\nдокумент два достаточной длины", encoding="utf-8")
     assert len(mem._walk_files(kb)) == 2
 
     def boom(*a, **k):
         raise OSError("git отсутствует")
 
     monkeypatch.setattr(rag.subprocess, "run", boom)
     assert len(mem._walk_files(kb)) == 2
+
+
+@needs_model
+def test_reindex_reuses_embeddings_of_unchanged_chunks(mem, monkeypatch):
+    """Переиндексация считает эмбеддинги только для НОВЫХ по тексту чанков.
+
+    Замер #73: `CHANGELOG.md` — 352 чанка × 2.2 с ≈ 775 с на переиндексацию при бюджете
+    прохода 300 с, а меняется в нём 0.6–11.2 % текстов. Ключ переиспользования — текст чанка,
+    не позиция: блок дописывается СВЕРХУ, у чанков меняется индекс, а не содержимое.
+    """
+    # Секции длиннее MD_MIN_MERGE: короткие чанкер сливает с соседними, и тогда при дописывании
+    # меняется ТЕКСТ соседа, а не только его позиция. На реальном CHANGELOG секции крупные —
+    # оттуда и 0.6–11.2 % новых текстов вместо 100 %.
+    head = "# Раздел А\n\n" + "первый раздел с подробным описанием и деталями. " * 12 + "\n\n"
+    tail = "## Раздел Б\n\n" + "второй раздел про совершенно другое, тоже подробно. " * 12 + "\n\n"
+    mem.index_file("/proj/a", "log.md", head + tail)
+    before = {r[0] for r in mem.conn.execute("SELECT text FROM file_chunks").fetchall()}
+
+    embedded: list[list[str]] = []
+    original = mem._embed
+    monkeypatch.setattr(mem, "_embed", lambda texts, **kw: embedded.append(list(texts)) or original(texts, **kw))
+
+    added = "# Новое\n\n" + "свежая запись, которой в прошлой версии файла не было. " * 12 + "\n\n"
+    n = mem.index_file("/proj/a", "log.md", added + head + tail)
+
+    assert n == len(before) + 1, "новый блок сверху добавляет чанк, старые сохраняются"
+    assert len(embedded) == 1
+    assert len(embedded[0]) == 1, f"переэмбеддить надо только новый чанк, а не {len(embedded[0])}"
+    assert "свежая запись" in embedded[0][0]
+    # старые тексты на месте, только с новыми chunk_id
+    after = {r[0] for r in mem.conn.execute("SELECT text FROM file_chunks").fetchall()}
+    assert before <= after
+
+
+@needs_model
+def test_reused_vectors_are_the_same_bytes(mem):
+    """Переложенный вектор обязан быть тем же, иначе поиск поедет незаметно."""
+    body = "# Тема\n\n" + "текст раздела достаточной длины для самостоятельного чанка. " * 12 + "\n\n"
+    mem.index_file("/proj/a", "doc.md", body)
+    old = mem.conn.execute("SELECT c.text, v.embedding FROM file_chunks c "
+                           "JOIN vec_files v USING(chunk_id)").fetchall()
+    mem.index_file("/proj/a", "doc.md",
+                   body + "## Хвост\n\n" + "дописанный раздел с новым текстом внутри. " * 12 + "\n")
+    new = {r["text"]: r["embedding"] for r in mem.conn.execute(
+        "SELECT c.text, v.embedding FROM file_chunks c JOIN vec_files v USING(chunk_id)").fetchall()}
+    for row in old:
+        assert new[row["text"]] == row["embedding"]


## Later history of the touched files on main (after this commit)

24 later commits touch these paths; the first 40 (oldest first):
71927b784 2026-08-04 docs: память воркера — автосборка CHANGELOG отменена, пишем руками
59d32c050 2026-08-06 #122: #122: AUTO_COMPACT_ENABLED=0 полностью выключает автокомпакт оркестратора
fa78c5b4a 2026-08-06 #129: #129: разбор потери точности больших чисел в аргументах tool-вызова — слой JS CLI, не наш
a376b2d75 2026-08-06 #130: #130: детектор целых > 2^53 в аргументах tool-вызова (имя тула, путь поля, значение)
15dd0e284 2026-08-07 #144: #144: TestPrecompactTimer пинит AUTO_COMPACT_ENABLED=1 — прогон не зависит от .env машины
8ebed917e 2026-08-07 #150: #150: молчащий источник usage пишет NULL и строку в журнал вместо нуля
8683e76b0 2026-08-07 #155: #155: отказ кибербез-фильтра — отдельный класс, подсказка по трём признакам, автооткат отравленной истории
639dc61d4 2026-08-07 #161: #161: отказ фильтра опознаётся по телу события и упавшему ходу; забракованный текст наружу не едет
503e71ec9 2026-08-12 #215: #215: account standalone Codex review usage
a41edae82 2026-08-13 #239: #239: preserve unknown costs in analytics
85b6174ee 2026-08-13 #246: #246: validate task creation project scopes
588c7817b 2026-08-13 #257: #257: suppress exact silent-turn marker in Telegram
83eda0e05 2026-08-13 #241: #241: tag the owner only when the turn calls notify_user
e55fb5bff 2026-08-13 #269: human refusal text and a durable inbox for messages that arrive during a restart
7c7c0de4b 2026-08-13 #269: drain the restart queue on every reopen, cap attempts, report undeliverable
3cfeb617a 2026-08-16 #297: #297: suppress silent marker auto-report
9947ae37c 2026-08-16 #300: #300: throttle background RAG embedding CPU
b604ef449 2026-08-17 #305: #305: serialize managed Codex cold starts
7f283eeed 2026-08-17 #316: #316: batch large mapped test subsets
bf70e3ad8 2026-08-18 #322: #322: balance merge gate batches
ce75f62a7 2026-08-27 Bound Orchestra native memory growth
4e5940ef6 2026-09-02 #433: research message provenance
498c0d149 2026-09-03 Orchestra: migrate project state to .orchestra
98574f427 2026-09-08 Replace duplicate task stores with private Git and one versioned SQLite projection

## Patches of the first 8 later commits, restricted to the touched paths (each capped at 150 lines)

### 71927b784 docs: память воркера — автосборка CHANGELOG отменена, пишем руками

diff --git a/docs/workers/back.md b/docs/workers/back.md
index 0261c72f4..ad76f6878 100644
--- a/docs/workers/back.md
+++ b/docs/workers/back.md
@@ -89,15 +89,18 @@
   `~/.local/state/orchestra/bug-inbox/records/` (0600, вне git — так задумано), куда `POST`
   кладёт каждый репорт отдельным файлом. **`BUGS.md` репозитория с 01.08 не пополняется:**
   всё новое лежит там, 7 репортов на момент проверки. Плюс `POST` возвращает агенту дословно
   `Read: /api/report_bug` (`mcp_stdio.py:1418`) — удаление сделало бы из этого ссылку на 404.
 
-- **CHANGELOG.md руками БОЛЬШЕ НЕ правится (#52).** Источник — ПЕРВАЯ СТРОКА
-  `docs/tasks/<id>/report.md`, она и есть запись changelog: формат `# #<id> — <текст>`, сборка
-  `uv run python scripts/build-changelog.py [--write --version vX.Y.Z]`. Проверить, как твоя
-  строка попадёт в файл, — сухим прогоном того же скрипта. Я по привычке начал писать блок
-  руками и поймал себя только на конфликте: механизм сменился под задачей.
+- **CHANGELOG.md пишется РУКАМИ.** Автосборка из отчётов задач (#52) существовала полдня и
+  отменена (`497db45`): `docs/tasks/*/report.md` содержат пути, IP, имена клиентов, а CHANGELOG
+  уезжает в публичный репозиторий — генерировать публичный файл из внутренних артефактов нельзя,
+  и удобство этого не перевешивает. Номер версии брать по main
+  (`git show main:CHANGELOG.md | grep -m1 '^## v'`), конфликт в одну точку вставки — известная
+  цена параллельной работы. **Урок шире файла: механизм может смениться и откатиться ПОСРЕДИ
+  твоей задачи** — я за сутки написал сюда обе версии правила. Прежде чем опираться на «как у нас
+  принято», проверь, что оно живо (`git log -1 -- <скрипт/файл>`), а не вспоминай.
 
 - **Тесты чанкера на КОРОТКИХ секциях врут.** Секция короче `MD_MIN_MERGE = 250` символов
   сливается с соседней, поэтому дописывание меняет ТЕКСТ соседнего чанка, а не только его
   позицию — мой тест на переиспользование эмбеддингов (#73) падал именно на этом, а не на коде.
   Для чанкерных тестов секции строить длиннее 250 символов, иначе проверяешь слияние, а не то,
### 59d32c050 #122: #122: AUTO_COMPACT_ENABLED=0 полностью выключает автокомпакт оркестратора

diff --git a/docs/workers/back.md b/docs/workers/back.md
index ad76f6878..e6afbee6b 100644
--- a/docs/workers/back.md
+++ b/docs/workers/back.md
@@ -98,10 +98,17 @@
   (`git show main:CHANGELOG.md | grep -m1 '^## v'`), конфликт в одну точку вставки — известная
   цена параллельной работы. **Урок шире файла: механизм может смениться и откатиться ПОСРЕДИ
   твоей задачи** — я за сутки написал сюда обе версии правила. Прежде чем опираться на «как у нас
   принято», проверь, что оно живо (`git log -1 -- <скрипт/файл>`), а не вспоминай.
 
+- **Правку текста делай Edit-инструментом, а не `python - <<EOF` с `str.replace` по вычисленной
+  строке.** В #122 я выбрал строку фильтром «содержит X, не содержит Y», промахнулся на другую и
+  затёр докстринг класса — файл перестал парситься целиком, а `pytest` показал SyntaxError совсем
+  не там, где я его искал. Если всё-таки скриптом: уникальный якорь + `assert old in s`, и
+  `open(..., encoding="utf-8")` явно на чтении И записи. Мутацию вносить только ASCII-комментарием
+  (`# MUTATION`) — тогда синтаксическая ошибка не может быть твоей.
+
 - **Тесты чанкера на КОРОТКИХ секциях врут.** Секция короче `MD_MIN_MERGE = 250` символов
   сливается с соседней, поэтому дописывание меняет ТЕКСТ соседнего чанка, а не только его
   позицию — мой тест на переиспользование эмбеддингов (#73) падал именно на этом, а не на коде.
   Для чанкерных тестов секции строить длиннее 250 символов, иначе проверяешь слияние, а не то,
   что хотел. Цена элемента меряется в ЧАНКАХ, не в килобайтах: 2.2 с/чанк, батчинг не помогает.
### fa78c5b4a #129: #129: разбор потери точности больших чисел в аргументах tool-вызова — слой JS CLI, не наш

diff --git a/docs/workers/back.md b/docs/workers/back.md
index e6afbee6b..ac047f8bb 100644
--- a/docs/workers/back.md
+++ b/docs/workers/back.md
@@ -137,5 +137,14 @@
   сравнивает `(path, methods)` со снимком и краснеет на ЛЮБОМ новом маршруте. Снимок
   регенерируется тем же кодом, что в тесте (`json.dumps(surface, indent=1, ensure_ascii=False)`);
   перед перезаписью распечатай симметричную разницу — в снимке не должно ПРОПАСТЬ ничего.
   FastAPI, в отличие от Starlette, HEAD к GET-маршруту сам не добавляет: нужен явный
   `@router.head`.
+
+- **Слой, округливший большое число, опознаётся по ФОРМАТУ текста, а не по коду.** Для
+  `1917704623170653147` (> 2^53): JS печатает `1917704623170653200` (кратчайшая round-trip
+  запись double), Python — либо `1.9177046231706532e+18` (`json.dumps` float'а), либо
+  `1917704623170653184` (`int(float(x))`, точное значение double). Три разных текста одного и
+  того же double → по строке в БД видно, чей это `JSON.stringify`. И помни: **Python
+  `json.loads` без `parse_int` разбирает целое ТОЧНО** (int произвольной точности), то есть
+  Python-слой целые ID не портит в принципе — виноват всегда кто-то другой.
+  Разбор — `docs/tasks/129/research.md`.
### a376b2d75 #130: #130: детектор целых > 2^53 в аргументах tool-вызова (имя тула, путь поля, значение)

diff --git a/docs/workers/back.md b/docs/workers/back.md
index ac047f8bb..725d43be1 100644
--- a/docs/workers/back.md
+++ b/docs/workers/back.md
@@ -146,5 +146,18 @@
   `1917704623170653184` (`int(float(x))`, точное значение double). Три разных текста одного и
   того же double → по строке в БД видно, чей это `JSON.stringify`. И помни: **Python
   `json.loads` без `parse_int` разбирает целое ТОЧНО** (int произвольной точности), то есть
   Python-слой целые ID не портит в принципе — виноват всегда кто-то другой.
   Разбор — `docs/tasks/129/research.md`.
+
+- **Чтобы увидеть, что CLI РЕАЛЬНО шлёт MCP-серверу, поднимай свой stdio MCP-сервер на 45 строк**
+  (`docs/tasks/130/probe_mcp.py`): пишет сырую строку JSON-RPC в файл ДО `json.loads`, параметр
+  объявляет без типа (`{"n": {}}`), чтобы принять и число, и строку. Подключается флагами, без
+  правки `~/.codex/config.toml`: `codex exec -c 'mcp_servers.probe.command="..."' -c
+  'mcp_servers.probe.args=["..."]'`. Стенд проверяется handshake'ом (`initialize` от
+  `codex-mcp-client`) ещё до ответа модели — то есть годность стенда видна, даже если квота
+  потом откажет. У Codex квота отдельная от Claude: `You've hit your usage limit ... try again at`.
+- **Цена рекурсивного обхода JSON меряется в ЭЛЕМЕНТАХ контейнеров, а не в байтах.** Реальный
+  аргумент tool-вызова на 157 КБ обходится за 2.2 µs (почти всё — одна строка), а список из
+  10 000 чисел — за 5 166 µs. Прежде чем резать глубину «ради производительности», померь на
+  РЕАЛЬНОЙ выборке из БД: 11 876 тел аргументов дали медиану 1.33 µs при 390 µs на `json.dumps`,
+  который в той же строке уже делается. Лимит без такого замера покупает 0 и продаёт полноту.
### 15dd0e284 #144: #144: TestPrecompactTimer пинит AUTO_COMPACT_ENABLED=1 — прогон не зависит от .env машины

diff --git a/docs/workers/back.md b/docs/workers/back.md
index 725d43be1..da3051e3c 100644
--- a/docs/workers/back.md
+++ b/docs/workers/back.md
@@ -159,5 +159,15 @@
 - **Цена рекурсивного обхода JSON меряется в ЭЛЕМЕНТАХ контейнеров, а не в байтах.** Реальный
   аргумент tool-вызова на 157 КБ обходится за 2.2 µs (почти всё — одна строка), а список из
   10 000 чисел — за 5 166 µs. Прежде чем резать глубину «ради производительности», померь на
   РЕАЛЬНОЙ выборке из БД: 11 876 тел аргументов дали медиану 1.33 µs при 390 µs на `json.dumps`,
   который в той же строке уже делается. Лимит без такого замера покупает 0 и продаёт полноту.
+
+- **Добавил в прод переменную окружения — застрахуй СУЩЕСТВУЮЩИЕ тесты от неё, а не только
+  напиши тесты НА неё.** #122: выключатель `AUTO_COMPACT_ENABLED` + 74 строки тестов на него,
+  а три старых теста `TestPrecompactTimer` стали читать значение из `.env` машины и покраснели
+  в main на боевой конфигурации (`AUTO_COMPACT_ENABLED=0` → `3 failed, 148 passed`). Шаг после
+  добавления флага: `grep -rn "<VAR>" tests/` даст ноль — это и есть симптом; искать надо тесты,
+  которые ходят по ЗАГЕЙЧЕННОМУ пути, и пинить им значение автоюз-фикстурой на КЛАССЕ.
+  На модуле нельзя: общая фикстура заглушит и тесты самого выключателя — проверяется мутацией
+  «гейт всегда True», после неё они обязаны краснеть (у меня 6 failed).
+  Приёмка такой правки — три прогона: `VAR=0`, `VAR=1` и `env -u VAR`.
### 8ebed917e #150: #150: молчащий источник usage пишет NULL и строку в журнал вместо нуля

diff --git a/docs/workers/back.md b/docs/workers/back.md
index da3051e3c..a7e985d12 100644
--- a/docs/workers/back.md
+++ b/docs/workers/back.md
@@ -169,5 +169,14 @@
   добавления флага: `grep -rn "<VAR>" tests/` даст ноль — это и есть симптом; искать надо тесты,
   которые ходят по ЗАГЕЙЧЕННОМУ пути, и пинить им значение автоюз-фикстурой на КЛАССЕ.
   На модуле нельзя: общая фикстура заглушит и тесты самого выключателя — проверяется мутацией
   «гейт всегда True», после неё они обязаны краснеть (у меня 6 failed).
   Приёмка такой правки — три прогона: `VAR=0`, `VAR=1` и `env -u VAR`.
+
+- **Признак «данных не было», выведенный из формы записи, проверяй на строках, где данные ТОЧНО
+  были.** В #150 напрашивалось «пустой `resets_at` при нулевом pct = источник молчал»; на живой
+  БД оказалось, что из 1033 строк с ОТВЕТИВШИМ провайдером 161 имеет пустой `resets_at`, и во
+  всех 161 pct = 0 — это ровно то, как выглядит настоящий ответ про только что сброшенное окно.
+  Признак пометил бы 161 честную строку как подделку. Порядок: сперва посчитай, сколько ЛОЖНЫХ
+  срабатываний даёт признак на заведомо хороших строках, и только потом предлагай миграцию.
+  Годный признак в этой задаче нашёлся независимым полем той же строки
+  (`provider_usage.anthropic.status == "unavailable"`), а не эвристикой.
### 8683e76b0 #155: #155: отказ кибербез-фильтра — отдельный класс, подсказка по трём признакам, автооткат отравленной истории

diff --git a/docs/workers/back.md b/docs/workers/back.md
index a7e985d12..bed1e80f0 100644
--- a/docs/workers/back.md
+++ b/docs/workers/back.md
@@ -178,5 +178,15 @@
   всех 161 pct = 0 — это ровно то, как выглядит настоящий ответ про только что сброшенное окно.
   Признак пометил бы 161 честную строку как подделку. Порядок: сперва посчитай, сколько ЛОЖНЫХ
   срабатываний даёт признак на заведомо хороших строках, и только потом предлагай миграцию.
   Годный признак в этой задаче нашёлся независимым полем той же строки
   (`provider_usage.anthropic.status == "unavailable"`), а не эвристикой.
+
+- **Стенограмму сессии Claude режет штатная `fork_session` из SDK — руками JSONL не трогать.**
+  `from claude_agent_sdk import fork_session, get_session_messages`;
+  `fork_session(sid, directory=<cwd>, up_to_message_id=<uuid>)` создаёт НОВЫЙ файл сессии со
+  свежими UUID, источник не трогает (проверил на живой: 1571 запись → форк 1067, отравленных
+  0). `get_session_messages(sid, directory=...)` даёт список с `uuid`/`message` для выбора точки
+  среза. Файлы лежат в `~/.claude/projects/<путь-с-дефисами>/<session_id>.jsonl`.
+  **Смены `s.session_id` НЕДОСТАТОЧНО:** клиент CLI persistent между ходами и держит старую
+  стенограмму, `_ensure_backend` возвращает живой backend не глядя на id. Нужен
+  `s._spawn_bg(s._disconnect_backend())` — иначе откат остаётся записью в журнале.
### 639dc61d4 #161: #161: отказ фильтра опознаётся по телу события и упавшему ходу; забракованный текст наружу не едет

diff --git a/docs/workers/back.md b/docs/workers/back.md
index bed1e80f0..c266676f5 100644
--- a/docs/workers/back.md
+++ b/docs/workers/back.md
@@ -188,5 +188,16 @@
   0). `get_session_messages(sid, directory=...)` даёт список с `uuid`/`message` для выбора точки
   среза. Файлы лежат в `~/.claude/projects/<путь-с-дефисами>/<session_id>.jsonl`.
   **Смены `s.session_id` НЕДОСТАТОЧНО:** клиент CLI persistent между ходами и держит старую
   стенограмму, `_ensure_backend` возвращает живой backend не глядя на id. Нужен
   `s._spawn_bg(s._disconnect_backend())` — иначе откат остаётся записью в журнале.
+
+- **Объяснение агенту про сработавший фильтр НЕ должно содержать того, что фильтр забраковал.**
+  Иначе объяснение само становится ядом: текст уезжает в контекст, агент цитирует его в ответе,
+  следующий ход падает снова. Наружу — только класс отказа, признаки для переформулировки,
+  `Request ID` и путь к файлу с сырым текстом; сам файл класть ВНЕ рабочего дерева
+  (`~/.local/state/orchestra/…`, как инбокс баг-репортов), а не в `docs/tasks/`.
+  **И общее, шире фильтров:** классификатор по фразе-маркеру ловит любого, кто эту фразу
+  ЦИТИРУЕТ. Нужен признак, что событие и ЕСТЬ сообщение источника (у CLI это префикс
+  `API Error:`, занимающий всё событие), плюс независимый структурный гард — «ход реально
+  упал» (`not ok`). Замер #161: без них успешный ход `end_turn` за $1.44 был принят за отказ,
+  и здоровой сессии срезали историю.