"""One-time YouGile → Orchestra import script.

Idempotent: safe to re-run. Existing tasks (by yougile_task_id) are skipped.
Run: python -m app.tm_import_yougile
"""

import json
import logging
import re
import sys
from pathlib import Path

import httpx

from app import tm
from app.tm_yougile import (
    YOUGILE_API, COLUMN_TO_STATUS, _headers,
)

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("tm-import")

PROJECT_ID = "parsing-hub"
PROJECT_NAME = "Парсинг"
PROJECT_SCOPE = "/mnt/data/Projects/Python/Parsing"
YOUGILE_PROJECT_ID = "09810660-0738-4965-bb03-39635b3d3054"
YOUGILE_BOARD_ID = "93007367-153b-4aec-8dd7-96dda1fd1f27"

CLIENT_ID = "aleksandr-kislinskiy"
CLIENT_NAME = "Александр Кислинский"

PAR_35_YOUGILE_ID = "9bffba06-5091-4f0e-abbe-0408130d6eba"
CONFLICTS_PATH = Path(__file__).parent.parent / "data" / "import_conflicts.json"


def _parse_title(title: str) -> tuple[str, int, int]:
    m = re.search(r"\|\s*(\d+)/(\d+)k\s*₽", title)
    if m:
        name = title[: m.start()].strip()
        paid_k = int(m.group(1))
        price_k = int(m.group(2))
        return name, paid_k * 1000, price_k * 1000
    return title.strip(), 0, 0


def _parse_par_number(id_task_project: str) -> int | None:
    if not id_task_project:
        return None
    m = re.search(r"(\d+)", id_task_project)
    return int(m.group(1)) if m else None


def _html_to_markdown(html: str) -> str:
    if not html:
        return ""
    try:
        from markdownify import markdownify
        return markdownify(html).strip()
    except ImportError:
        text = re.sub(r"<br\s*/?>", "\n", html)
        text = re.sub(r"<[^>]+>", "", text)
        return text.strip()


def fetch_all_tasks_for_column(column_id: str) -> list[dict]:
    tasks = []
    offset = 0
    limit = 50
    while True:
        url = f"{YOUGILE_API}/tasks?columnId={column_id}&offset={offset}&limit={limit}"
        resp = httpx.get(url, headers=_headers(), timeout=15)
        if resp.status_code != 200:
            logger.error("API error: %d %s", resp.status_code, resp.text[:200])
            break
        data = resp.json()
        content = data.get("content", [])
        if not content:
            break
        tasks.extend(content)
        offset += limit
        if len(content) < limit:
            break
    return tasks


def run_import():
    conn = tm._conn()
    conn.execute("BEGIN IMMEDIATE")

    try:
        tm.ensure_project(
            conn, PROJECT_ID, PROJECT_NAME, PROJECT_SCOPE,
            YOUGILE_PROJECT_ID, YOUGILE_BOARD_ID, yougile_enabled=True, prefix="PAR",
        )
        tm.ensure_client(conn, CLIENT_ID, CLIENT_NAME, PROJECT_ID)

        conflicts = []
        imported = 0
        skipped = 0
        total_yougile = 0
        total_paid_import = 0
        tasks_to_pay = []

        all_yougile_tasks = []
        for column_id, status in COLUMN_TO_STATUS.items():
            tasks_in_col = fetch_all_tasks_for_column(column_id)
            total_yougile += len(tasks_in_col)
            logger.info("Column %s (%s): %d tasks", column_id[:8], status, len(tasks_in_col))
            for yt in tasks_in_col:
                yt["_status"] = status
                all_yougile_tasks.append(yt)

        known_pars = set()
        for yt in all_yougile_tasks:
            par_num = _parse_par_number(yt.get("idTaskProject", ""))
            if par_num is not None:
                known_pars.add(par_num)

        for yt in all_yougile_tasks:
            yougile_id = yt["id"]
            if yougile_id == PAR_35_YOUGILE_ID:
                skipped += 1
                continue

            existing = tm.get_task_by_yougile_id(conn, yougile_id)
            if existing:
                skipped += 1
                continue

            id_task_project = yt.get("idTaskProject", "")
            par_num = _parse_par_number(id_task_project)

            if par_num is not None:
                existing_par = tm.get_task_by_par(conn, par_num)
                if existing_par and existing_par["yougile_task_id"] != yougile_id:
                    conflicts.append({
                        "par": par_num,
                        "yougile_id": yougile_id,
                        "existing_yougile_id": existing_par["yougile_task_id"],
                        "title": yt.get("title", ""),
                    })
                    continue

            title, paid_rub, price_rub = _parse_title(yt.get("title", ""))
            description = _html_to_markdown(yt.get("description", ""))
            status = yt["_status"]

            task = tm.create_task(
                conn, PROJECT_ID, title,
                price_rub=price_rub,
                description=description,
                status=status,
                yougile_task_id=yougile_id,
                par_number=par_num,
            )

            if paid_rub > 0:
                total_paid_import += paid_rub
                tasks_to_pay.append((task["id"], task["par_number"], paid_rub, task["created_at"]))

            tm.log_sync(conn, task["id"], "import", 0, "ok")
            imported += 1

        if total_paid_import > 0:
            now = tm._now()
            import_payment_id = conn.execute(
                "INSERT INTO tm_payments (client_id, amount_rub, date, note, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (CLIENT_ID, total_paid_import, now[:10], "YouGile import (consolidated)", now),
            ).lastrowid
            for task_id, par_num, paid_rub, _ in tasks_to_pay:
                conn.execute(
                    "INSERT INTO tm_payment_allocations (payment_id, task_id, amount_rub, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (import_payment_id, task_id, paid_rub, now),
                )
                conn.execute(
                    "UPDATE tm_tasks SET paid_rub = ? WHERE id = ?",
                    (paid_rub, task_id),
                )

        our_count = conn.execute("SELECT COUNT(*) FROM tm_tasks").fetchone()[0]

        conn.commit()

        logger.info("Import complete: %d imported, %d skipped, %d conflicts", imported, skipped, len(conflicts))
        logger.info("YouGile total: %d, Our DB: %d (PAR-35 excluded)", total_yougile, our_count)

        if conflicts:
            CONFLICTS_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFLICTS_PATH.write_text(json.dumps(conflicts, indent=2, ensure_ascii=False))
            logger.warning("Conflicts written to %s — resolve before cutover!", CONFLICTS_PATH)
        elif CONFLICTS_PATH.exists():
            CONFLICTS_PATH.unlink()

        return {
            "imported": imported,
            "skipped": skipped,
            "conflicts": len(conflicts),
            "yougile_total": total_yougile,
            "our_total": our_count,
        }

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    result = run_import()
    print(json.dumps(result, indent=2))
