# Task Manager for Orchestra — Design Document

**Date:** 2026-05-14
**Status:** Draft (post-Codex review v2)
**Author:** research-taskmanager worker

---

## 1. Data Model

### SQLite Schema (same `data/orchestra.db`)

```sql
CREATE TABLE tm_projects (
    id TEXT PRIMARY KEY,              -- "parsing-hub", "ai-assistants", etc.
    name TEXT NOT NULL,               -- Display name: "Парсинг"
    scope TEXT UNIQUE,                 -- Orchestra scope path for dashboard mapping (1:1)
    yougile_project_id TEXT,
    yougile_board_id TEXT,
    created_at TEXT NOT NULL
);

-- Atomic PAR number generator (avoids race on MAX+1)
CREATE TABLE tm_par_sequence (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- Singleton row
    next_value INTEGER NOT NULL DEFAULT 1
);
INSERT OR IGNORE INTO tm_par_sequence (id, next_value) VALUES (1, 1);

CREATE TABLE tm_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    par_number INTEGER NOT NULL UNIQUE,
    project_id TEXT NOT NULL REFERENCES tm_projects(id),
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',        -- Markdown (NOT HTML)
    price_rub INTEGER NOT NULL DEFAULT 0 CHECK (price_rub >= 0),
    paid_rub INTEGER NOT NULL DEFAULT 0 CHECK (paid_rub >= 0),
    status TEXT NOT NULL DEFAULT 'backlog',
    assignee TEXT NOT NULL DEFAULT '',
    yougile_task_id TEXT UNIQUE,                -- UUID for sync (UNIQUE prevents dupes)
    sync_revision INTEGER NOT NULL DEFAULT 0,   -- Incremented on every mutation, sync uses latest
    worker_session_id TEXT,
    git_commits TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    paid_at TEXT,
    CHECK (status IN ('backlog', 'new', 'in_progress', 'done', 'paid', 'cancelled')),
    CHECK (paid_rub <= price_rub)
);
CREATE INDEX idx_tm_tasks_status ON tm_tasks(status);
CREATE INDEX idx_tm_tasks_project ON tm_tasks(project_id, status);
CREATE INDEX idx_tm_tasks_par ON tm_tasks(par_number);
CREATE INDEX idx_tm_tasks_yougile ON tm_tasks(yougile_task_id);

CREATE TABLE tm_clients (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    project_id TEXT NOT NULL REFERENCES tm_projects(id),
    balance_rub INTEGER NOT NULL DEFAULT 0,     -- Positive = prepayment, 0 = even
    created_at TEXT NOT NULL
);

-- Payment ledger: only REAL incoming money from client
CREATE TABLE tm_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL REFERENCES tm_clients(id),
    amount_rub INTEGER NOT NULL CHECK (amount_rub > 0),
    date TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

-- How payments are allocated to tasks.
-- Balance = SUM(payments.amount_rub) - SUM(allocations.amount_rub)
-- Prepayment deductions create allocations against the ORIGINAL payment (FIFO),
-- NOT fake "virtual" payments. This keeps the formula clean.
CREATE TABLE tm_payment_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id INTEGER NOT NULL REFERENCES tm_payments(id),
    task_id INTEGER NOT NULL REFERENCES tm_tasks(id),
    amount_rub INTEGER NOT NULL CHECK (amount_rub > 0),
    created_at TEXT NOT NULL
);
CREATE INDEX idx_tm_alloc_payment ON tm_payment_allocations(payment_id);
CREATE INDEX idx_tm_alloc_task ON tm_payment_allocations(task_id);

-- YouGile sync queue + log
CREATE TABLE tm_sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER REFERENCES tm_tasks(id),
    direction TEXT NOT NULL DEFAULT 'push',
    action TEXT NOT NULL,
    sync_revision INTEGER,                     -- Task revision at time of sync
    payload TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',     -- 'pending', 'ok', 'error', 'skipped'
    error TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX idx_tm_sync_task ON tm_sync_log(task_id);
CREATE INDEX idx_tm_sync_pending ON tm_sync_log(status) WHERE status = 'pending';
```

### Key Design Decisions

1. **Price in integer rubles** — no kopeks, prices are always in thousands (5k, 20k). Stored as `5000`, `20000`. Display as `5k`, `20k`. No floating point.

2. **`paid_rub` on task** — denormalized for fast display. Equals `SUM(amount_rub) FROM tm_payment_allocations WHERE task_id = ?`. Recalculated + asserted on every payment operation.

3. **`balance_rub` on client** — denormalized. `SUM(payments.amount_rub) - SUM(allocations.amount_rub)`. Positive = prepayment available. **Never negative** — we don't do credit. Asserted on every payment operation.

4. **PAR number via `tm_par_sequence`** — atomic: `UPDATE tm_par_sequence SET next_value = next_value + 1 RETURNING next_value - 1` inside `BEGIN IMMEDIATE`. No race conditions on concurrent creates.

5. **Markdown description** — stored as markdown. Converted to HTML only on YouGile sync push.

6. **No "testing" or "postponed" status** — YouGile has 8 columns, we have 6 statuses. Mapping:
   - YouGile "Ресёрч" / "Отложено" → our `backlog`
   - YouGile "Новые" → our `new`
   - YouGile "В работе" / "Тестирование" → our `in_progress`
   - YouGile "Сделано" → our `done`
   - YouGile "Оплачено" → our `paid`
   - YouGile "Отменено" → our `cancelled`

7. **No virtual payments for prepayment deductions** — when a task moves to `done` and client has balance, we allocate from the earliest unallocated payment (FIFO), not create a fake incoming payment. This keeps the balance formula `SUM(payments) - SUM(allocations)` always correct.

8. **`sync_revision`** — monotonically increasing per task. Every mutation bumps it. Sync worker only pushes the latest revision, skipping stale ones. Prevents out-of-order updates in YouGile.

9. **`yougile_task_id UNIQUE`** — prevents duplicate creates at DB level. Before creating in YouGile, `yougile_find_by_par()` searches YouGile by `idTaskProject=PAR-N` to handle the crash-between-create-and-save scenario (create succeeded remotely but yougile_task_id wasn't saved locally).

10. **Scope → project mapping** — `tm_projects.scope` maps Orchestra scope to project_id so dashboard knows which tasks to show for current orchestrator.

---

## 2. MCP Tools Spec

All tools added to `app/mcp_stdio.py` alongside existing Orchestra tools. They call Orchestra HTTP API endpoints (new routes in `app/main.py`).

### 2.1 `task_create`

```python
@mcp.tool()
async def task_create(
    title: str,
    project: str,           # "parsing-hub", "ai-assistants", etc.
    price: int = 0,          # Price in thousands (e.g. 20 = 20,000₽). 0 is valid (no price set).
    description: str = "",   # Markdown
    assignee: str = "",
    status: str = "new",
) -> str:
    """Create a new task. Returns PAR number and task details."""
```

**Returns:**
```json
{
  "par": "PAR-42",
  "id": 42,
  "title": "SEO Hardening",
  "project": "parsing-hub",
  "price_rub": 20000,
  "status": "new"
}
```

**Side effects:**
- Auto-assigns next PAR number (atomic via `tm_par_sequence`)
- Triggers YouGile sync (creates task in mapped column)
- If status = "in_progress" and price > 0, notifies TG

### 2.2 `task_update`

```python
@mcp.tool()
async def task_update(
    par: str,                    # "PAR-42" or just "42"
    title: str | None = None,    # None = don't change
    description: str | None = None,
    price: int | None = None,    # New price in thousands. None = don't change. 0 = set to zero.
    status: str | None = None,
    assignee: str | None = None,
) -> str:
    """Update an existing task. Only provided fields are changed.

    Price change rules:
    - Cannot lower price below paid_rub (would violate paid <= price constraint)
    - Raising price on 'paid' task moves it back to 'done' (reopens debt)
    - Cannot change price on 'cancelled' task
    """
```

**Returns:**
```json
{
  "par": "PAR-42",
  "updated": ["title", "status"],
  "old_status": "new",
  "new_status": "in_progress",
  "price_rub": 20000,
  "paid_rub": 0,
  "sync_status": "ok"
}
```

**Side effects:**
- Status change → YouGile sync (move to mapped column)
- Status → "done" + client has balance → auto-allocate from prepayment
- Status → "done" → TG notification
- Title/price change → YouGile sync (update title format)
- Every mutation bumps `sync_revision`

### 2.3 `task_list`

```python
@mcp.tool()
async def task_list(
    project: str = "",       # Filter by project (empty = all)
    status: str = "",        # Filter by status (empty = all)
    assignee: str = "",
) -> str:
    """List tasks with optional filters. Returns summary per task."""
```

**Returns:**
```json
{
  "tasks": [
    {
      "par": "PAR-42",
      "title": "SEO Hardening",
      "project": "parsing-hub",
      "price": "20k",
      "paid": "0k",
      "debt": "20k",
      "status": "done",
      "assignee": "maxim"
    }
  ],
  "count": 1,
  "total_debt": "20k"
}
```

### 2.4 `task_get`

```python
@mcp.tool()
async def task_get(par: str) -> str:
    """Get full task details including payment history and linked commits."""
```

**Returns:**
```json
{
  "par": "PAR-42",
  "title": "SEO Hardening",
  "description": "## What\n9 SEO items...",
  "project": "parsing-hub",
  "price_rub": 20000,
  "paid_rub": 15000,
  "debt_rub": 5000,
  "status": "done",
  "assignee": "maxim",
  "created_at": "2026-05-01",
  "completed_at": "2026-05-10",
  "payments": [
    {"date": "2026-05-05", "amount": 15000, "payment_id": 3}
  ],
  "commits": ["a1b2c3d", "e4f5g6h"],
  "yougile_id": "uuid-here",
  "sync_revision": 5
}
```

### 2.5 `payment_receive`

```python
@mcp.tool()
async def payment_receive(
    amount: int,             # In thousands (e.g. 30 = 30,000₽)
    client: str = "aleksandr-kislinskiy",
    date: str = "",          # YYYY-MM-DD, defaults to today
    note: str = "",
) -> str:
    """Record incoming payment. Auto-distributes to done tasks (smallest debt first).
    If no done tasks with debt — records as prepayment on client balance.

    Entire operation runs in a single BEGIN IMMEDIATE transaction.
    YouGile sync and TG notification happen AFTER commit."""
```

**Returns:**
```json
{
  "payment_id": 7,
  "amount_rub": 30000,
  "date": "2026-05-14",
  "distributions": [
    {"par": "PAR-38", "title": "Mobile auth", "allocated": 8000, "was_debt": 8000, "now_paid": true},
    {"par": "PAR-42", "title": "SEO Hardening", "allocated": 20000, "was_debt": 20000, "now_paid": true},
    {"par": "PAR-45", "title": "API refactor", "allocated": 2000, "was_debt": 5000, "now_paid": false}
  ],
  "tasks_closed": 2,
  "remainder_to_balance": 0,
  "new_balance": 0,
  "total_debt_remaining": 3000,
  "sync_status": "pending"
}
```

**Algorithm:**
```
BEGIN IMMEDIATE

1. INSERT INTO tm_payments
2. Get all tasks with status='done' AND price_rub > 0 AND paid_rub < price_rub
3. Sort by debt ASC (smallest first — close maximum tasks)
4. For each task:
   a. debt = price_rub - paid_rub
   b. If remainder >= debt: allocate debt, paid_rub = price_rub,
      status='paid', set paid_at
   c. If remainder < debt: allocate remainder, paid_rub += remainder, stop
   d. remainder -= allocated
   e. Bump sync_revision
5. If remainder > 0: UPDATE tm_clients balance_rub += remainder
6. Sanity checks (see 4.4)
7. If any check fails → ROLLBACK, return error
COMMIT

-- AFTER commit (non-transactional):
8. Enqueue YouGile sync for each affected task + PAR-35
9. TG notification with breakdown
```

### 2.6 `payment_status`

```python
@mcp.tool()
async def payment_status(
    client: str = "aleksandr-kislinskiy",
) -> str:
    """Get payment overview: balance, total debt, recent payments."""
```

**Returns:**
```json
{
  "client": "Александр Кислинский",
  "balance_rub": 5000,
  "balance_display": "5k",
  "total_debt_rub": 25000,
  "total_debt_display": "25k",
  "net_position": -20000,
  "tasks_with_debt": [
    {"par": "PAR-45", "title": "API refactor", "debt": "5k"},
    {"par": "PAR-50", "title": "Dashboard", "debt": "20k"}
  ],
  "recent_payments": [
    {"id": 7, "date": "2026-05-14", "amount": "30k", "note": "оплата за май"}
  ]
}
```

---

## 3. YouGile Sync Strategy

### 3.1 Direction

**One-way: Orchestra → YouGile (master)**. Orchestra is source of truth. YouGile is a read-only mirror for the client.

### 3.2 Initial Import

One-time script (`app/tm_import_yougile.py`) that:

1. Fetches ALL tasks from ALL columns via YouGile API **with pagination** (loop until empty page, offset-based: `?columnId={id}&offset={n}&limit=50`)
2. For each task:
   - Parse title: extract name and `X/Yk ₽` if present
   - Parse `idTaskProject` → PAR number (e.g. "PAR-199" → 199)
   - **Dedup by `yougile_task_id`** — if already imported (UNIQUE constraint), skip
   - **PAR collision check** — if parsed PAR already exists with a different `yougile_task_id`, write to conflict report and skip (don't overwrite)
   - Map columnId → our status
   - Convert HTML description → markdown (via `markdownify`)
   - Insert into `tm_tasks` with `yougile_task_id` set
3. Import PAR-35 payment journal:
   - Parse description to extract payment history
   - Create `tm_payments` and `tm_payment_allocations` records
   - Calculate client balance
4. Set `tm_par_sequence.next_value` to `MAX(imported par_number) + 1`
5. Log everything to `tm_sync_log` with action='import'
6. **Verification step**: compare count per column (YouGile API vs our DB). Report discrepancies.
7. Write conflict report to `data/import_conflicts.json` if any PAR collisions found

**Import is idempotent** — safe to re-run. Existing tasks (by `yougile_task_id`) are skipped. Cutover only proceeds when conflict report is empty.

### 3.3 Ongoing Sync (Push)

Every task mutation bumps `sync_revision` and enqueues a sync job:

```python
async def yougile_sync_task(task_id: int):
    task = get_task_by_id(task_id)

    if not task['yougile_task_id']:
        # Search YouGile by idTaskProject before creating to prevent dupes on retry
        existing = await yougile_find_by_par(f"PAR-{task['par_number']}")
        if existing:
            # Task already exists in YouGile (previous create succeeded but we crashed before saving ID)
            with db_transaction():
                update_task_yougile_id(task_id, existing['id'])
                log_sync(task_id, 'create', task['sync_revision'], 'ok')
            # Refetch task with updated yougile_task_id before pushing
            task = get_task_by_id(task_id)
            await yougile_update(task)
            return

        result = await yougile_create(task)
        with db_transaction():
            update_task_yougile_id(task_id, result['id'])
            log_sync(task_id, 'create', task['sync_revision'], 'ok')
    else:
        # Only push if this is the latest revision
        latest = get_latest_pending_revision(task_id)
        if latest and latest > task['sync_revision']:
            log_sync(task_id, 'update', task['sync_revision'], 'skipped')
            return
        await yougile_update(task)
        log_sync(task_id, 'update', task['sync_revision'], 'ok')
```

**Title format on push:**
```python
def format_yougile_title(task):
    if task['price_rub'] > 0:
        x = task['paid_rub'] // 1000
        y = task['price_rub'] // 1000
        return f"{task['title']} | {x}/{y}k ₽"
    return task['title']
```

**Description conversion:**
```python
import markdown
html = markdown.markdown(task['description'])
```

**Status → Column mapping:**
```python
STATUS_TO_COLUMN = {
    'backlog':     '0096a255-f3b9-4da0-a07d-070599a1bc9e',  # Ресёрч
    'new':         'c6c65162-fac6-4d9d-915a-18036d22dfc0',  # Новые
    'in_progress': '7bca2e03-971c-4adc-8ad6-9c0d3f2a85cb',  # В работе
    'done':        'caf3e21c-7ec8-4dce-b70c-0019290019ea',  # Сделано
    'paid':        '7d179d60-20a3-4ba3-a2b0-d9011db6e300',  # Оплачено
    'cancelled':   'fff16786-0ed9-4f53-a779-3809d3911565',  # Отменено
}
```

### 3.4 Sync Implementation

```python
# In app/tm_yougile.py

YOUGILE_API = "https://yougile.com/api-v2"
YOUGILE_TOKEN = os.environ.get("YOUGILE_SEEDON_TOKEN", "")

async def yougile_push(task: dict, action: str) -> dict:
    headers = {
        "Authorization": f"Bearer {YOUGILE_TOKEN}",
        "Content-Type": "application/json"
    }
    if action == 'create':
        body = {
            "title": format_yougile_title(task),
            "description": md_to_html(task['description']),
            "columnId": STATUS_TO_COLUMN[task['status']],
            "idTaskProject": f"PAR-{task['par_number']}",  # Stable external ID for dedup on retry
        }
        # POST /tasks
    elif action == 'update':
        body = {
            "title": format_yougile_title(task),
            "columnId": STATUS_TO_COLUMN[task['status']],
            "completed": task['price_rub'] > 0 and task['paid_rub'] == task['price_rub'],
        }
        # PUT /tasks/{yougile_task_id}
```

### 3.5 PAR-35 Sync (Legacy Compat)

PAR-35 is special — it's the payment journal in YouGile. On every payment:

1. Update PAR-35 title: `Информация об оплатах | {balance}k баланс`
2. Append to PAR-35 description (parse existing HTML, add new line to "Пополнения")
3. Add comment to PAR-35 with distribution details (HTML format from payment skill)
4. Update "Сделано" column title: `Сделано → {total_debt}k ₽`

**Idempotency for PAR-35:**
- Include `payment_id` in every journal line and comment: `[#7]`
- Before appending, check if `[#7]` already exists in description/comments
- If found → skip (retry of already-applied payment)
- All 4 steps in a single `yougile_update_par35(payment_id)` function — partial failure retries the whole set

### 3.6 Error Handling

**For regular task sync (title, status):**
- Log to `tm_sync_log` with status='pending'
- On success → status='ok'
- On failure → status='error', retry_count++
- Retry up to 3 times with 5s delay
- After 3 failures → stay as 'error', dashboard shows sync warning icon
- Don't block the main operation

**For payment sync (PAR-35 + task status changes):**
- Same retry logic but **dashboard prominently shows** pending payment syncs
- `payment_receive` returns `sync_status: "pending"` if any sync failed
- Manual retry button in dashboard for failed syncs
- TG notification still fires regardless of sync status (user needs to know about payment)

---

## 4. Payment Engine

### 4.1 Auto-Distribution Algorithm

```python
def distribute_payment(conn, payment_id: int, client_id: str, amount_rub: int) -> dict:
    """Distribute payment to done tasks, smallest debt first.

    MUST be called inside BEGIN IMMEDIATE transaction (conn).
    YouGile sync happens AFTER caller commits.
    """
    # 1. Get done tasks with debt, ordered by debt ASC
    tasks = conn.execute("""
        SELECT * FROM tm_tasks
        WHERE status = 'done'
          AND price_rub > 0
          AND project_id IN (SELECT project_id FROM tm_clients WHERE id = ?)
          AND paid_rub < price_rub
        ORDER BY (price_rub - paid_rub) ASC, par_number ASC
    """, (client_id,)).fetchall()

    remainder = amount_rub
    distributions = []

    for task in tasks:
        if remainder <= 0:
            break
        debt = task['price_rub'] - task['paid_rub']
        allocated = min(debt, remainder)

        conn.execute("""
            INSERT INTO tm_payment_allocations (payment_id, task_id, amount_rub, created_at)
            VALUES (?, ?, ?, ?)
        """, (payment_id, task['id'], allocated, now()))

        new_paid = task['paid_rub'] + allocated
        new_status = 'paid' if new_paid == task['price_rub'] else 'done'
        conn.execute("""
            UPDATE tm_tasks
            SET paid_rub = ?, status = ?, paid_at = ?,
                updated_at = ?, sync_revision = sync_revision + 1
            WHERE id = ?
        """, (new_paid, new_status,
              now() if new_status == 'paid' else None,
              now(), task['id']))

        distributions.append({
            'par': f"PAR-{task['par_number']}",
            'title': task['title'],
            'allocated': allocated,
            'was_debt': debt,
            'now_paid': new_status == 'paid',
            'task_id': task['id'],
        })
        remainder -= allocated

    # 2. Remainder → client balance (prepayment)
    if remainder > 0:
        conn.execute(
            "UPDATE tm_clients SET balance_rub = balance_rub + ? WHERE id = ?",
            (remainder, client_id))

    return {'distributions': distributions, 'remainder_to_balance': remainder}
```

### 4.2 Auto-Deduct from Prepayment

When a task moves to `done` and client has positive balance. Uses FIFO allocation from existing payments (no virtual payments).

```python
def auto_deduct_prepayment(conn, task_id: int):
    """Allocate prepayment balance to newly-done task.

    Finds unallocated payment funds FIFO and creates allocations.
    No new tm_payments rows — just allocations against existing payments.
    """
    task = get_task(conn, task_id)
    client = get_client_for_project(conn, task['project_id'])
    if not client or client['balance_rub'] <= 0:
        return

    debt = task['price_rub'] - task['paid_rub']
    if debt <= 0:
        return

    deduct = min(debt, client['balance_rub'])
    remaining_deduct = deduct

    # Find payments with unallocated funds, oldest first (FIFO)
    payments = conn.execute("""
        SELECT p.id, p.amount_rub,
               COALESCE(SUM(a.amount_rub), 0) as allocated
        FROM tm_payments p
        LEFT JOIN tm_payment_allocations a ON a.payment_id = p.id
        WHERE p.client_id = ?
        GROUP BY p.id
        HAVING p.amount_rub > COALESCE(SUM(a.amount_rub), 0)
        ORDER BY p.id ASC
    """, (client['id'],)).fetchall()

    for payment in payments:
        if remaining_deduct <= 0:
            break
        available = payment['amount_rub'] - payment['allocated']
        take = min(available, remaining_deduct)

        conn.execute("""
            INSERT INTO tm_payment_allocations (payment_id, task_id, amount_rub, created_at)
            VALUES (?, ?, ?, ?)
        """, (payment['id'], task_id, take, now()))

        remaining_deduct -= take

    # Update task
    new_paid = task['paid_rub'] + deduct
    new_status = 'paid' if new_paid == task['price_rub'] else 'done'
    conn.execute("""
        UPDATE tm_tasks SET paid_rub=?, status=?, paid_at=?,
               updated_at=?, sync_revision = sync_revision + 1
        WHERE id=?
    """, (new_paid, new_status,
          now() if new_status == 'paid' else None,
          now(), task_id))

    # Update client balance
    conn.execute(
        "UPDATE tm_clients SET balance_rub = balance_rub - ? WHERE id=?",
        (deduct, client['id']))
```

### 4.3 Balance Tracking

Balance is always derivable and asserted:
```sql
SELECT
    (SELECT COALESCE(SUM(amount_rub), 0) FROM tm_payments WHERE client_id = ?)
    -
    (SELECT COALESCE(SUM(a.amount_rub), 0) FROM tm_payment_allocations a
     JOIN tm_payments p ON a.payment_id = p.id WHERE p.client_id = ?)
AS computed_balance
```

Denormalized `balance_rub` on client for fast reads. **Every payment operation** recalculates and asserts `computed_balance == balance_rub`.

### 4.4 Sanity Checks

Every payment operation runs inside `BEGIN IMMEDIATE` and asserts BEFORE commit:

1. `SUM(allocations for payment) <= payment.amount_rub` (no over-allocation per payment)
2. `task.paid_rub == SUM(allocations for task)` (denorm matches reality)
3. `client.balance_rub == computed_balance` (denorm matches formula)
4. No task has `paid_rub > price_rub`
5. All tasks with `price_rub > 0 AND paid_rub == price_rub` have `status = 'paid'` (tasks with `price_rub = 0` are excluded — free tasks don't participate in payment logic)
6. `client.balance_rub >= 0` (no negative balance / credit)

If ANY check fails → `ROLLBACK`, return error with details of which check failed.

### 4.5 Cancellation Rules

- **`done` → `cancelled`** (unpaid task): allowed, no financial impact
- **`done` → `cancelled`** (partially paid, `paid_rub > 0`): **forbidden** — must void allocations first via manual intervention. MCP tool returns error.
- **`paid` → `cancelled`**: **forbidden** via `task_update`. Requires a separate `task_void` operation (out of MVP scope — handle manually if ever needed).

---

## 5. Dashboard UI Spec

### 5.1 Sidebar Tabs

The left panel (currently "FILES") gets two tabs:

```html
<div id="left-panel" class="w-[250px] border-r border-slate-800/50 flex flex-col">
    <div class="flex border-b border-slate-800/50">
        <button data-tab="files"
            class="flex-1 px-3 py-2 text-xs font-bold text-slate-400 hover:text-white
                   border-b-2 border-transparent tab-active:border-indigo-500">
            FILES
        </button>
        <button data-tab="tasks"
            class="flex-1 px-3 py-2 text-xs font-bold text-slate-400 hover:text-white
                   border-b-2 border-transparent tab-active:border-indigo-500">
            TASKS
        </button>
    </div>
    <div id="file-panel-content" class="flex-1 overflow-y-auto text-xs p-1">
        <div id="file-tree">...</div>
    </div>
    <div id="tasks-panel-content" class="flex-1 overflow-y-auto text-xs p-1 hidden">
        ...
    </div>
</div>
```

### 5.2 Tasks Panel Layout

```
┌─────────────────────────┐
│ FILES │ TASKS            │
├─────────────────────────┤
│ 💰 Balance: 5k ₽       │
│ 📊 Debt: 25k ₽         │
│ ⚠️ 2 sync pending       │  ← shown only if failed syncs exist
├─────────────────────────┤
│ ▸ IN PROGRESS (3)       │
│   PAR-50 Dashboard  20k │
│   PAR-51 API auth   8k  │
│   PAR-52 Mobile     15k │
│ ▸ DONE (2)      → 25k ₽│
│   PAR-42 SEO     5/20k  │
│   PAR-45 Refactor 0/5k  │
│ ▸ NEW (4)               │
│   PAR-55 Import     10k │
│   ...                    │
│ ▾ BACKLOG (12)          │
│ ▾ PAID (28)             │
└─────────────────────────┘
```

**Status group colors:**
- `in_progress` → blue dot
- `done` → amber dot (has debt indicator)
- `new` → white dot
- `backlog` → gray dot (collapsed by default)
- `paid` → green dot (collapsed by default)
- `cancelled` → red dot (collapsed by default)

### 5.3 Click-to-Inject

Click task → inject `[PAR-{N}] ` into chat input. Double-click → open task detail modal.

### 5.4 Task Detail Modal

Reuses existing modal pattern (like prompt-modal). Shows: status, price, paid/debt, assignee, project, dates, rendered markdown description, payment history, linked commits.

### 5.5 Data Fetching

```
GET /api/tm/tasks?scope=/mnt/data/Projects/Python/Parsing
```

Scope maps to `tm_projects.scope` → returns tasks for that project. Frontend fetches on tab switch + polls every 30s when tasks tab is active.

---

## 6. Architecture

### 6.1 Where Does This Code Live?

**Inside Orchestra, not a separate server.** Shares DB, dashboard, MCP, TG bridge.

### 6.2 File Structure

```
app/
├── tm.py                  # Task manager core: CRUD, payment engine, sanity checks
├── tm_yougile.py          # YouGile sync: push, import, PAR-35 compat
├── tm_import_yougile.py   # One-time import script (run standalone)
├── db.py                  # +tm_ tables in init_db() and _migrate()
├── mcp_stdio.py           # +task_create, task_update, etc.
├── main.py                # +/api/tm/* routes (note: /api/tm/ prefix, not /api/tasks/)
├── tg_bridge.py           # +task notification handlers
└── static/js/
    └── app.js             # +tasks panel, tab switching, detail modal
```

### 6.3 Route Structure

```python
# Task CRUD — under /api/tm/ prefix to avoid collision with future routes
GET    /api/tm/tasks                  # List (with filters)
POST   /api/tm/tasks                  # Create
GET    /api/tm/tasks/{par}            # Get by PAR number
PUT    /api/tm/tasks/{par}            # Update

# Payments
POST   /api/tm/payments               # Record payment
GET    /api/tm/payments/status         # Balance overview
GET    /api/tm/payments/history        # Payment history

# Sync
POST   /api/tm/sync/import            # Trigger initial import
GET    /api/tm/sync/log                # View sync history
POST   /api/tm/sync/retry/{id}         # Retry failed sync
```

**Note:** Static routes (`/status`, `/history`, `/import`, `/log`) registered BEFORE parametric `/{par}` to avoid FastAPI path interception.

### 6.4 Module Responsibilities

**`app/tm.py`** — Pure business logic:
- `create_task()`, `update_task()`, `list_tasks()`, `get_task()`
- `receive_payment()`, `get_payment_status()`
- `auto_deduct_prepayment()`
- All sanity checks
- Takes `conn` parameter — caller manages transactions
- No HTTP, no YouGile, no TG

**`app/tm_yougile.py`** — YouGile sync layer:
- `yougile_push()` — create/update task in YouGile
- `yougile_import_all()` — one-time import with pagination + dedup
- `yougile_update_par35()` — idempotent payment journal compat
- `yougile_update_column_title()` — "Сделано → Xk ₽"

### 6.5 Integration Points

**Worker spawn → task status:**
```python
async def spawn_worker_for_task(name, task_id, ...):
    task = tm.get_task(task_id)
    tm.update_task(task_id, status='in_progress', worker_session_id=session.id)
    await spawn_worker(name, task=f"[PAR-{task['par_number']}] ...", ...)
```

**Worker DONE → task status:**
```python
if "DONE:" in message and session.worker_session_id:
    task = tm.get_task_by_worker(session.id)
    if task:
        tm.update_task(task['id'], status='done')
```

**Git commit → task link:**
```python
par_refs = re.findall(r'PAR-(\d+)', commit_message)
for par_num in par_refs:
    task = tm.get_task_by_par(int(par_num))
    if task:
        commits = json.loads(task['git_commits'])
        commits.append(commit_sha)
        tm.update_task(task['id'], git_commits=json.dumps(commits))
```

---

## 7. Implementation Plan

### Phase 1: Data Layer + Core CRUD (1-2 hours)
- Add `tm_*` tables to `app/db.py` (schema + migration)
- Create `app/tm.py` with task CRUD + payment engine
- Unit tests for payment distribution algorithm (especially edge cases: 0 price, concurrent, partial)
- **No UI, no sync, no MCP tools yet**

### Phase 2: MCP Tools + API Routes (1-2 hours)
- Add HTTP routes to `app/main.py` (`/api/tm/*`)
- Add MCP tools to `app/mcp_stdio.py` (6 tools)
- Test via MCP from orchestrator session
- **Agents can now create/manage tasks**

### Phase 3: YouGile Sync (2-3 hours)
- Create `app/tm_yougile.py` (push logic, PAR-35 compat with idempotency)
- Create `app/tm_import_yougile.py` (paginated import with dedup + collision report)
- Run import against real YouGile data, verify counts
- Test push on task create/update
- **YouGile becomes a mirror**

### Phase 4: Dashboard UI (1-2 hours)
- Add tasks tab to sidebar in `dashboard.html`
- Task list with status groups, click-to-inject
- Task detail modal
- Payment status header + sync status indicator
- **Visible in browser**

### Phase 5: Orchestra Integration (1 hour)
- Worker spawn with `task_id` → auto in_progress
- Worker DONE detection → auto done
- Git commit PAR-XXX detection → link commits
- **Full automation loop**

### Phase 6: TG Notifications (30 min)
- Task status change → TG message
- Payment received → TG breakdown message
- **Client stays informed**

**Total: ~8-10 hours of implementation work.**

---

## 8. Migration Plan

### Step 1: Import (Day 1)
1. Deploy the new tables (Phase 1)
2. Run `tm_import_yougile.py` — paginated, deduped, with conflict report
3. Verify: task count per column matches YouGile (automated check)
4. Verify: PAR numbers, prices, paid amounts all match
5. Verify: client balance matches PAR-35 journal
6. **If conflict report is non-empty → resolve manually before proceeding**

### Step 2: Parallel Operation (Day 2-3)
1. Deploy MCP tools (Phase 2) + sync (Phase 3)
2. Both systems active: Orchestra is master, pushes to YouGile
3. Continue using YouGile for client visibility
4. Create new tasks via Orchestra MCP tools (they sync to YouGile)
5. Payment via `payment_receive` MCP tool (syncs to YouGile PAR-35)

### Step 3: Cutover (Day 4+)
1. Stop using YouGile MCP tools in Parsing project
2. Update Parsing CLAUDE.md: replace YouGile skill with Orchestra task tools
3. Update payment skill to use `payment_receive` instead of manual YouGile updates
4. Keep YouGile sync running (client still reads it)
5. Deploy dashboard UI (Phase 4)

### What Breaks During Migration
- **Nothing.** YouGile stays readable throughout. Orchestra writes, YouGile displays.
- Payment format in YouGile stays identical (PAR-35 journal, comments, title format)
- PAR numbers preserved from import

### Rollback Plan
1. Stop YouGile sync (comment out push calls)
2. Re-enable YouGile MCP tools in Parsing
3. Data is safe in both systems — import was additive

---

## Appendix A: Status Transition Rules

```
backlog ──→ new ──→ in_progress ──→ done ──→ paid
  │                    │              │
  └──→ cancelled ←─────┘              │
                                      └──→ cancelled (only if paid_rub == 0)
```

**Allowed transitions:**
- `backlog` → `new`, `cancelled`
- `new` → `in_progress`, `backlog`, `cancelled`
- `in_progress` → `done`, `new`, `cancelled`
- `done` → `paid` (only via payment engine, not manual), `in_progress` (reopened), `cancelled` (only if `paid_rub == 0`)
- `paid` → **terminal** (no transitions; void/refund out of MVP scope)
- `cancelled` → `new` (un-cancel)

**Auto-transitions:**
- `payment_receive` moves `done` → `paid` (when fully paid)
- `spawn_worker(task_id=X)` moves task → `in_progress`
- Worker reports DONE → task → `done`
- Task moves to `done` + client balance > 0 → may auto-move to `paid`

**Forbidden transitions (enforced in `task_update`):**
- Any status → `paid` (only payment engine can do this)
- `paid` → anything
- `done`/`paid` → `cancelled` when `paid_rub > 0` (has financial records)

---

## Appendix B: YouGile API Reference (Used)

```
GET    /tasks?columnId={id}&offset={n}&limit=50  # List tasks (paginated)
GET    /tasks/{id}                                 # Get task details
POST   /tasks                                      # Create task
PUT    /tasks/{id}                                  # Update task
PUT    /columns/{id}                                # Update column title
POST   /tasks/{id}/comments                        # Add comment

Headers: Authorization: Bearer {token}
Content-Type: application/json
```

---

## Appendix C: TG Notification Templates

### Task Status Change
```
📋 PAR-42 "SEO Hardening" → in_progress
👤 Assignee: maxim
💰 Price: 20k ₽
```

### Payment Received
```
💰 Оплата 30 000 ₽ от Александр Кислинский

Распределение:
✅ PAR-38 Mobile auth — 8k (закрыт)
✅ PAR-42 SEO Hardening — 20k (закрыт)
📝 PAR-45 API refactor — 2k из 5k (частично)

Закрыто задач: 2
Баланс: 0 ₽
Остаток долга: 3k ₽
```
