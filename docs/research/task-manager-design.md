# Task Manager for Orchestra — Design Document

**Date:** 2026-05-14
**Status:** Draft
**Author:** research-taskmanager worker

---

## 1. Data Model

### SQLite Schema (same `data/orchestra.db`)

```sql
-- Projects / boards for multi-project support
CREATE TABLE tm_projects (
    id TEXT PRIMARY KEY,              -- "parsing-hub", "ai-assistants", etc.
    name TEXT NOT NULL,               -- Display name: "Парсинг"
    yougile_project_id TEXT,          -- UUID for YouGile sync
    yougile_board_id TEXT,            -- UUID for YouGile sync
    created_at TEXT NOT NULL
);

-- Task statuses as a progression
-- backlog → new → in_progress → done → paid → cancelled
-- "testing" omitted from core — maps to in_progress substatus
-- "postponed" omitted — maps to backlog

CREATE TABLE tm_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    par_number INTEGER NOT NULL UNIQUE, -- Auto-increment PAR-1, PAR-2, ...
    project_id TEXT NOT NULL REFERENCES tm_projects(id),
    title TEXT NOT NULL,                -- "SEO Hardening zahoron.ru"
    description TEXT DEFAULT '',        -- Markdown (NOT HTML)
    price_rub INTEGER DEFAULT 0,        -- Price in rubles (integer, no kopeks)
    paid_rub INTEGER DEFAULT 0,         -- Amount paid so far
    status TEXT NOT NULL DEFAULT 'backlog',
    assignee TEXT DEFAULT '',           -- "aleksandr", "maxim", etc.
    yougile_task_id TEXT,              -- UUID for sync
    worker_session_id TEXT,            -- FK to sessions.id when assigned to worker
    git_commits TEXT DEFAULT '[]',     -- JSON array of commit SHAs linked to this task
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,                 -- When moved to done
    paid_at TEXT,                      -- When fully paid (moved to paid)
    CHECK (status IN ('backlog', 'new', 'in_progress', 'done', 'paid', 'cancelled')),
    CHECK (paid_rub >= 0 AND paid_rub <= price_rub)
);
CREATE INDEX idx_tm_tasks_status ON tm_tasks(status);
CREATE INDEX idx_tm_tasks_project ON tm_tasks(project_id, status);
CREATE INDEX idx_tm_tasks_par ON tm_tasks(par_number);
CREATE INDEX idx_tm_tasks_yougile ON tm_tasks(yougile_task_id);

-- Clients (for now just Александр Кислинский)
CREATE TABLE tm_clients (
    id TEXT PRIMARY KEY,              -- "aleksandr-kislinskiy"
    name TEXT NOT NULL,               -- "Александр Кислинский"
    project_id TEXT NOT NULL REFERENCES tm_projects(id),
    balance_rub INTEGER DEFAULT 0,    -- Positive = prepayment, negative = debt
    created_at TEXT NOT NULL
);

-- Payment events (incoming money)
CREATE TABLE tm_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id TEXT NOT NULL REFERENCES tm_clients(id),
    amount_rub INTEGER NOT NULL,      -- Always positive (incoming)
    date TEXT NOT NULL,                -- Payment date (YYYY-MM-DD)
    note TEXT DEFAULT '',              -- "аванс", "оплата за май"
    created_at TEXT NOT NULL           -- When recorded in system
);

-- How each payment was distributed to tasks
CREATE TABLE tm_payment_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id INTEGER NOT NULL REFERENCES tm_payments(id),
    task_id INTEGER NOT NULL REFERENCES tm_tasks(id),
    amount_rub INTEGER NOT NULL,       -- How much of this payment went to this task
    created_at TEXT NOT NULL
);
CREATE INDEX idx_tm_alloc_payment ON tm_payment_allocations(payment_id);
CREATE INDEX idx_tm_alloc_task ON tm_payment_allocations(task_id);

-- YouGile sync log (outbound pushes)
CREATE TABLE tm_sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER REFERENCES tm_tasks(id),
    direction TEXT NOT NULL DEFAULT 'push', -- 'push' (our→yougile) or 'pull' (initial import)
    action TEXT NOT NULL,               -- 'create', 'update', 'move', 'import'
    payload TEXT DEFAULT '',            -- JSON of what was sent/received
    status TEXT DEFAULT 'ok',           -- 'ok', 'error', 'skipped'
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_tm_sync_task ON tm_sync_log(task_id);
```

### Key Design Decisions

1. **Price in integer rubles** — no kopeks, prices are always in thousands (5k, 20k). Stored as `5000`, `20000`. Display as `5k`, `20k`. No floating point.

2. **`paid_rub` on task** — denormalized for fast display. Always equals `SUM(amount_rub) FROM tm_payment_allocations WHERE task_id = ?`. Recalculated on every payment operation.

3. **`balance_rub` on client** — denormalized. `SUM(payments) - SUM(allocations)`. Positive = prepayment available.

4. **PAR number separate from ID** — `id` is internal autoincrement, `par_number` is the external-facing sequential number. Both auto-increment but `par_number` is the one shown in UI/commits.

5. **Markdown description** — stored as markdown. Converted to HTML only on YouGile sync push. No HTML in our DB ever.

6. **No "testing" or "postponed" status** — YouGile has 8 columns, we have 6 statuses. Mapping:
   - YouGile "Ресёрч" / "Отложено" → our `backlog`
   - YouGile "Новые" → our `new`
   - YouGile "В работе" / "Тестирование" → our `in_progress`
   - YouGile "Сделано" → our `done`
   - YouGile "Оплачено" → our `paid`
   - YouGile "Отменено" → our `cancelled`

7. **Git commits as JSON array** — simple. No need for a separate table for a handful of commits per task.

---

## 2. MCP Tools Spec

All tools added to `app/mcp_stdio.py` alongside existing Orchestra tools. They call Orchestra HTTP API endpoints (new routes in `app/main.py`).

### 2.1 `task_create`

```python
@mcp.tool()
async def task_create(
    title: str,
    project: str,           # "parsing-hub", "ai-assistants", etc.
    price: int = 0,          # Price in thousands (e.g. 20 = 20,000₽)
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
- Auto-assigns next PAR number
- Triggers YouGile sync (creates task in mapped column)
- If status = "in_progress" and price > 0, notifies TG

### 2.2 `task_update`

```python
@mcp.tool()
async def task_update(
    par: str,                # "PAR-42" or just "42"
    title: str = "",
    description: str = "",
    price: int = 0,          # New price in thousands (0 = don't change)
    status: str = "",        # New status (empty = don't change)
    assignee: str = "",
) -> str:
    """Update an existing task. Only provided fields are changed."""
```

**Returns:**
```json
{
  "par": "PAR-42",
  "updated": ["title", "status"],
  "old_status": "new",
  "new_status": "in_progress",
  "price_rub": 20000,
  "paid_rub": 0
}
```

**Side effects:**
- Status change → YouGile sync (move to mapped column)
- Status → "done" + client has balance → auto-allocate from prepayment
- Status → "done" → TG notification
- Title/price change → YouGile sync (update title format)

### 2.3 `task_list`

```python
@mcp.tool()
async def task_list(
    project: str = "",       # Filter by project (empty = all)
    status: str = "",        # Filter by status (empty = all)
    assignee: str = "",      # Filter by assignee
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
  "yougile_id": "uuid-here"
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
    If no done tasks with debt — records as prepayment on client balance."""
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
  "total_debt_remaining": 3000
}
```

**Algorithm:**
```
1. Get all tasks with status='done' AND paid_rub < price_rub
2. Sort by debt ASC (smallest first — close maximum tasks)
3. For each task:
   a. debt = price_rub - paid_rub
   b. If remainder >= debt: allocate debt, set paid_rub = price_rub,
      move to status='paid', set paid_at
   c. If remainder < debt: allocate remainder, paid_rub += remainder, stop
   d. remainder -= allocated
4. If remainder > 0: add to client balance (prepayment)
5. Record payment + allocations in DB
6. Trigger YouGile sync for each affected task
7. TG notification with breakdown
```

**Side effects:**
- Fully paid tasks → status='paid', YouGile sync to "Оплачено"
- Partially paid → YouGile title updated with new X/Y
- TG notification with full breakdown
- YouGile PAR-35 description + comment updated (legacy compat)

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

1. Fetches ALL tasks from ALL columns via YouGile API
2. For each task:
   - Parse title: extract name and `X/Yk ₽` if present
   - Parse `idTaskProject` → PAR number (e.g. "PAR-199" → 199)
   - Map columnId → our status
   - Convert HTML description → markdown (via `markdownify` or simple regex for YouGile's basic HTML)
   - Insert into `tm_tasks` with `yougile_task_id` set
3. Import PAR-35 payment journal:
   - Parse description to extract payment history
   - Create `tm_payments` and `tm_payment_allocations` records
   - Calculate client balance
4. Set `par_number` sequence to `MAX(imported) + 1`
5. Log everything to `tm_sync_log` with action='import'

**PAR number handling during import:**
- YouGile's `idTaskProject` is "PAR-{N}" — extract N, use as `par_number`
- If YouGile task has no idTaskProject or unparseable → assign new PAR number from sequence

### 3.3 Ongoing Sync (Push)

Every task mutation (create, update status, update title/price/paid) triggers an async push to YouGile:

```python
async def yougile_sync_task(task_id: int):
    task = get_task_by_id(task_id)
    if not task['yougile_task_id']:
        # Create new task in YouGile
        result = await yougile_create(task)
        update_task_yougile_id(task_id, result['id'])
    else:
        # Update existing task
        await yougile_update(task)
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
# markdown → HTML for YouGile
import markdown
html = markdown.markdown(task['description'])
```

**Status → Column mapping:**
```python
STATUS_TO_COLUMN = {
    'backlog': '0096a255-f3b9-4da0-a07d-070599a1bc9e',   # Ресёрч
    'new':     'c6c65162-fac6-4d9d-915a-18036d22dfc0',   # Новые
    'in_progress': '7bca2e03-971c-4adc-8ad6-9c0d3f2a85cb', # В работе
    'done':    'caf3e21c-7ec8-4dce-b70c-0019290019ea',   # Сделано
    'paid':    '7d179d60-20a3-4ba3-a2b0-d9011db6e300',   # Оплачено
    'cancelled': 'fff16786-0ed9-4f53-a779-3809d3911565', # Отменено
}
```

### 3.4 Sync Implementation

```python
# In app/tm_yougile.py

YOUGILE_API = "https://yougile.com/api-v2"
YOUGILE_TOKEN = os.environ.get("YOUGILE_SEEDON_TOKEN", "")
# The token from the feature request: ekgJK3AW2f+...

async def yougile_push(task: dict, action: str) -> dict:
    """Push task state to YouGile. Returns sync result."""
    headers = {
        "Authorization": f"Bearer {YOUGILE_TOKEN}",
        "Content-Type": "application/json"
    }

    if action == 'create':
        body = {
            "title": format_yougile_title(task),
            "description": md_to_html(task['description']),
            "columnId": STATUS_TO_COLUMN[task['status']],
        }
        # POST /tasks
        ...
    elif action == 'update':
        body = {}
        # Only include changed fields
        body["title"] = format_yougile_title(task)
        body["columnId"] = STATUS_TO_COLUMN[task['status']]
        body["completed"] = task['paid_rub'] == task['price_rub'] and task['price_rub'] > 0
        # PUT /tasks/{yougile_task_id}
        ...
```

### 3.5 PAR-35 Sync (Legacy Compat)

PAR-35 is special — it's the payment journal in YouGile. On every payment:

1. Update PAR-35 title: `Информация об оплатах | {balance}k баланс`
2. Append to PAR-35 description (parse existing HTML, add new line to "Пополнения")
3. Add comment to PAR-35 with distribution details (HTML format from payment skill)
4. Update "Сделано" column title: `Сделано → {total_debt}k ₽`

This maintains backward compatibility so the client sees the same format in YouGile.

### 3.6 Conflict Handling

No conflicts possible — we're one-way push. If YouGile update fails:
- Log error to `tm_sync_log`
- Retry once after 5s
- If still fails → leave in sync log with status='error', continue
- Don't block the main operation (task update succeeds even if sync fails)

---

## 4. Payment Engine

### 4.1 Auto-Distribution Algorithm

```python
async def distribute_payment(payment_id: int, client_id: str, amount_rub: int) -> dict:
    """Distribute payment to done tasks, smallest debt first."""

    # 1. Get done tasks with debt, ordered by debt ASC
    tasks = db.execute("""
        SELECT * FROM tm_tasks
        WHERE status = 'done'
          AND project_id IN (SELECT project_id FROM tm_clients WHERE id = ?)
          AND price_rub > paid_rub
        ORDER BY (price_rub - paid_rub) ASC, par_number ASC
    """, (client_id,)).fetchall()

    remainder = amount_rub
    distributions = []

    for task in tasks:
        if remainder <= 0:
            break
        debt = task['price_rub'] - task['paid_rub']
        allocated = min(debt, remainder)

        # Record allocation
        db.execute("""
            INSERT INTO tm_payment_allocations (payment_id, task_id, amount_rub, created_at)
            VALUES (?, ?, ?, ?)
        """, (payment_id, task['id'], allocated, now()))

        # Update task paid amount
        new_paid = task['paid_rub'] + allocated
        new_status = 'paid' if new_paid == task['price_rub'] else 'done'
        db.execute("""
            UPDATE tm_tasks
            SET paid_rub = ?, status = ?, paid_at = ?, updated_at = ?
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
        })

        # Trigger YouGile sync
        await yougile_sync_task(task['id'])

        remainder -= allocated

    # 2. Remainder → client balance (prepayment)
    if remainder > 0:
        db.execute("""
            UPDATE tm_clients SET balance_rub = balance_rub + ? WHERE id = ?
        """, (remainder, client_id))

    return {
        'distributions': distributions,
        'remainder_to_balance': remainder,
    }
```

### 4.2 Auto-Deduct from Prepayment

When a task moves to `done` and client has positive balance:

```python
async def auto_deduct_prepayment(task_id: int):
    """If client has prepayment balance, auto-pay task on completion."""
    task = get_task(task_id)
    client = get_client_for_project(task['project_id'])
    if not client or client['balance_rub'] <= 0:
        return

    debt = task['price_rub'] - task['paid_rub']
    if debt <= 0:
        return

    deduct = min(debt, client['balance_rub'])

    # Create a "virtual" payment from balance
    payment_id = db.execute("""
        INSERT INTO tm_payments (client_id, amount_rub, date, note, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (client['id'], deduct, today(), 'списание из аванса', now())).lastrowid

    # Allocate to task
    db.execute("""
        INSERT INTO tm_payment_allocations (payment_id, task_id, amount_rub, created_at)
        VALUES (?, ?, ?, ?)
    """, (payment_id, task_id, deduct, now()))

    # Update task
    new_paid = task['paid_rub'] + deduct
    new_status = 'paid' if new_paid == task['price_rub'] else 'done'
    db.execute("UPDATE tm_tasks SET paid_rub=?, status=?, updated_at=? WHERE id=?",
               (new_paid, new_status, now(), task_id))

    # Update client balance
    db.execute("UPDATE tm_clients SET balance_rub = balance_rub - ? WHERE id=?",
               (deduct, client['id']))

    # Sync
    await yougile_sync_task(task_id)
```

### 4.3 Balance Tracking

Balance is always derivable:
```sql
-- Client balance = total payments - total allocations
SELECT
    (SELECT COALESCE(SUM(amount_rub), 0) FROM tm_payments WHERE client_id = ?)
    -
    (SELECT COALESCE(SUM(amount_rub), 0) FROM tm_payment_allocations a
     JOIN tm_payments p ON a.payment_id = p.id WHERE p.client_id = ?)
AS computed_balance
```

But we keep `balance_rub` on client for fast reads. Recalculate + assert on every payment operation.

### 4.4 Sanity Checks

Every payment operation runs these assertions:
1. `SUM(allocations for payment) <= payment.amount_rub`
2. `task.paid_rub == SUM(allocations for task)`
3. `client.balance_rub == SUM(payments) - SUM(allocations)`
4. No task has `paid_rub > price_rub`
5. All tasks with `paid_rub == price_rub` have `status = 'paid'`

If any check fails → rollback, log error, return error to caller.

---

## 5. Dashboard UI Spec

### 5.1 Sidebar Tabs

The left panel (currently "FILES") gets two tabs:

```html
<div id="left-panel" class="w-[250px] border-r border-slate-800/50 flex flex-col">
    <!-- Tab bar -->
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

    <!-- Files panel (existing) -->
    <div id="file-panel-content" class="flex-1 overflow-y-auto text-xs p-1">
        <div id="file-tree">...</div>
    </div>

    <!-- Tasks panel (new) -->
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

**Each task item:**
```html
<div class="task-item flex items-center gap-1.5 px-2 py-1 hover:bg-slate-800/50
            rounded cursor-pointer text-xs" data-par="42">
    <span class="text-slate-500 font-mono shrink-0">42</span>
    <span class="truncate flex-1">SEO Hardening</span>
    <span class="text-amber-400 shrink-0">5/20k</span>
</div>
```

**Status group colors:**
- `in_progress` → blue dot
- `done` → amber dot (has debt indicator)
- `new` → white dot
- `backlog` → gray dot (collapsed by default)
- `paid` → green dot (collapsed by default)
- `cancelled` → red dot (collapsed by default)

### 5.3 Click-to-Inject

When user clicks a task in the sidebar:

```javascript
document.addEventListener('click', e => {
    const taskEl = e.target.closest('.task-item');
    if (!taskEl) return;

    const par = taskEl.dataset.par;
    const input = document.getElementById('chat-input');

    // Inject task reference into chat input
    const ref = `[PAR-${par}] `;
    if (!input.value.includes(`PAR-${par}`)) {
        input.value = ref + input.value;
        input.focus();
    }
});
```

On double-click → open task detail modal.

### 5.4 Task Detail Modal

Reuses the existing modal pattern (like prompt-modal):

```
┌──────────────────────────────────────┐
│ PAR-42 SEO Hardening zahoron.ru   ✕ │
├──────────────────────────────────────┤
│ Status: done     Price: 20k ₽       │
│ Paid: 5/20k      Debt: 15k ₽       │
│ Assignee: maxim   Project: parsing  │
│ Created: 2026-05-01                  │
│ Completed: 2026-05-10               │
│──────────────────────────────────────│
│ ## Description                       │
│ 9 SEO items for zahoron.ru...       │
│ (rendered markdown)                  │
│──────────────────────────────────────│
│ ## Payments                          │
│ • 2026-05-05: +15k (payment #3)     │
│──────────────────────────────────────│
│ ## Commits                           │
│ • a1b2c3d — fix meta tags           │
│ • e4f5g6h — add sitemap             │
└──────────────────────────────────────┘
```

### 5.5 Data Fetching

New API endpoint:
```
GET /api/tasks?project=parsing-hub&scope=/mnt/data/Projects/Python/Parsing
```

Frontend fetches on tab switch + polls every 30s when tasks tab is active. No SSE needed — tasks change infrequently.

---

## 6. Architecture

### 6.1 Where Does This Code Live?

**Inside Orchestra, not a separate server.** Reasons:

1. Needs access to `sessions` table (worker↔task linking)
2. Needs SSE/websocket for dashboard (already exists)
3. Needs MCP tools (already in `mcp_stdio.py`)
4. Needs TG bridge (already integrated)
5. No reason for a separate process — it's a data module, not a service

### 6.2 File Structure

```
app/
├── tm.py                  # Task manager core: CRUD, payment engine
├── tm_yougile.py          # YouGile sync: push, import, PAR-35 compat
├── tm_import_yougile.py   # One-time import script
├── db.py                  # +tm_ tables in init_db() and _migrate()
├── mcp_stdio.py           # +task_create, task_update, etc.
├── main.py                # +/api/tasks/* routes
├── tg_bridge.py           # +task notification handlers
└── static/js/
    └── app.js             # +tasks panel, tab switching, detail modal
```

### 6.3 Module Responsibilities

**`app/tm.py`** — Pure business logic:
- `create_task()`, `update_task()`, `list_tasks()`, `get_task()`
- `receive_payment()`, `get_payment_status()`
- `auto_deduct_prepayment()`
- All sanity checks
- No HTTP, no YouGile, no TG — those are triggered by callers

**`app/tm_yougile.py`** — YouGile sync layer:
- `yougile_push()` — create/update task in YouGile
- `yougile_import_all()` — one-time import
- `yougile_update_par35()` — legacy payment journal compat
- `yougile_update_column_title()` — "Сделано → Xk ₽"
- All YouGile API calls go through here

**`app/main.py`** — New routes:
```python
# Task CRUD
GET    /api/tasks                    # List (with filters)
GET    /api/tasks/{par}              # Get by PAR number
POST   /api/tasks                    # Create
PUT    /api/tasks/{par}              # Update

# Payments
POST   /api/payments                 # Record payment
GET    /api/payments/status          # Balance overview
GET    /api/payments/history         # Payment history

# Sync
POST   /api/tasks/import-yougile    # Trigger initial import
GET    /api/tasks/sync-log           # View sync history
```

**`app/mcp_stdio.py`** — MCP tools call the HTTP API:
```python
@mcp.tool()
async def task_create(...):
    return await _api("POST", "/api/tasks", json={...})
```

### 6.4 Integration Points

**Worker spawn → task status:**
```python
# In manager.py, spawn_worker flow:
async def spawn_worker_for_task(name, task_id, ...):
    task = tm.get_task(task_id)
    # Auto-set in_progress
    tm.update_task(task_id, status='in_progress', worker_session_id=session.id)
    # Spawn worker with task context in system prompt
    await spawn_worker(name, task=f"[PAR-{task['par_number']}] {task['description']}", ...)
```

**Worker DONE → task status:**
```python
# In message handler, when worker reports DONE:
if "DONE:" in message and session.worker_session_id:
    task = tm.get_task_by_worker(session.id)
    if task:
        tm.update_task(task['id'], status='done')
        # Triggers auto_deduct_prepayment if applicable
```

**Git commit → task link:**
```python
# In merge_worker or commit detection:
# Parse commit messages for PAR-XXX pattern
import re
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
- Unit tests for payment distribution algorithm
- **No UI, no sync, no MCP tools yet**

### Phase 2: MCP Tools + API Routes (1-2 hours)
- Add HTTP routes to `app/main.py` (`/api/tasks/*`, `/api/payments/*`)
- Add MCP tools to `app/mcp_stdio.py` (6 tools)
- Test via MCP from orchestrator session
- **Agents can now create/manage tasks**

### Phase 3: YouGile Sync (2-3 hours)
- Create `app/tm_yougile.py` (push logic, PAR-35 compat)
- Create `app/tm_import_yougile.py` (one-time import)
- Run import against real YouGile data
- Test push on task create/update
- **YouGile becomes a mirror**

### Phase 4: Dashboard UI (1-2 hours)
- Add tasks tab to sidebar in `dashboard.html`
- Task list with status groups, click-to-inject
- Task detail modal
- Payment status header
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
2. Run `tm_import_yougile.py` to pull ALL YouGile tasks into our DB
3. Verify: task count, PAR numbers, prices, paid amounts all match
4. Verify: client balance matches PAR-35 journal

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
- The only change for Parsing orchestrator: different tool names (`task_create` vs `mcp__yougile__create_task`)

### Rollback Plan
If something goes wrong:
1. Stop YouGile sync (comment out push calls)
2. Re-enable YouGile MCP tools in Parsing
3. Data is safe in both systems — import was additive

---

## Appendix A: Status Transition Rules

```
backlog ──→ new ──→ in_progress ──→ done ──→ paid
  │                    │              │
  └──→ cancelled ←─────┘              │
                                      └──→ cancelled (refund scenario)
```

**Allowed transitions:**
- `backlog` → `new`, `cancelled`
- `new` → `in_progress`, `backlog`, `cancelled`
- `in_progress` → `done`, `new`, `cancelled`
- `done` → `paid` (only via payment), `in_progress` (reopened), `cancelled`
- `paid` → (terminal, no transitions except `cancelled` for refund)
- `cancelled` → `new` (un-cancel)

**Auto-transitions:**
- `payment_receive` can move `done` → `paid`
- `spawn_worker(task_id=X)` moves task → `in_progress`
- Worker reports DONE → task moves → `done`
- Task moves to `done` + client balance > 0 → may auto-move to `paid`

---

## Appendix B: YouGile API Reference (Used)

```
GET    /tasks?columnId={id}&limit=30    # List tasks in column
GET    /tasks/{id}                       # Get task details
POST   /tasks                            # Create task
PUT    /tasks/{id}                       # Update task
PUT    /columns/{id}                     # Update column title
POST   /tasks/{id}/comments             # Add comment to task

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
