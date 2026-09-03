# Prime Agent: механика по коду

Разбор репозитория `PrimeIntellect-ai/prime-agent`, коммит `0e0d2339` (Wed Aug 5 2026), `packages/coding-agent` v0.7.0.
Все пути — от корня клона (`/tmp/prime-agent`). Каждое утверждение = цитата кода + `путь:строка`.
Где заявку блога подтвердить кодом не удалось — так и написано.

---

## 1. Persistent IPython kernel

### Один тул, поле `code` — подтверждается

Весь список тулов, которые видит модель, — ровно одна запись:

```ts
export type ToolName = "ipython";
export const allToolNames: Set<ToolName> = new Set(["ipython"]);
```
`packages/coding-agent/src/core/tools/index.ts:46-47`

Схема тула — обычный JSON Schema (typebox), одно строковое поле:

```ts
const ipythonSchema = Type.Object({
	code: Type.String({
		description:
			"Python scratchpad code or `%%bash` shell cells to execute in the agent kernel. ...",
	}),
});
```
`packages/coding-agent/src/core/tools/ipython.ts:143-148`

```ts
	return {
		name: "ipython",
		label: "ipython",
		description:
			"Execute Python scratchpad code and `%%bash` shell cells in a persistent IPython kernel. ...",
		// The kernel is single-threaded — pi must not run two ipython calls in parallel within a batch.
		executionMode: "sequential",
		parameters: ipythonSchema,
```
`packages/coding-agent/src/core/tools/ipython.ts:625-633`

То есть никакой особой механики под провайдеров нет: это обычный tool-call с одним аргументом,
который любой провайдер отдаёт своим штатным форматом. Файлы `core/tools/bash.ts` и
`core/tools/edit.ts` в репозитории есть, но в `createAllTools` они не попадают —
`createAllTools` возвращает `{ ipython }` (`core/tools/index.ts:76-80`); наружу они экспортируются
только через SDK для эмбеддеров/расширений (`core/sdk.ts:21`, `:109-110`).
Редактирование файлов реализовано скиллом `skills/edit`, который печатает диффы через
`display_data` с MIME `application/vnd.prime-agent.diff+json` (`core/kernel/index.ts:110`).

Документация это же и заявляет: «The default RLM runtime exposes one built-in model tool: `ipython`»
(`packages/coding-agent/docs/rlm.md:33`).

### Где поднимается процесс и по какому протоколу

**Не `jupyter_client`.** Своя реализация Jupyter wire protocol 5.3 на ZeroMQ прямо в Node:

```ts
import { Dealer, Subscriber } from "zeromq";
...
const DELIM = Buffer.from("<IDS|MSG>");
const PROTOCOL_VERSION = "5.3";
```
`packages/coding-agent/src/core/kernel/index.ts:10,25-26`

Спавн — штатный `ipykernel_launcher` с временным connection-файлом:

```ts
const kernel = spawn(python, ["-m", "ipykernel_launcher", "-f", connection.path], {
	cwd: this.options.cwd,
	env: this.options.env ? { ...process.env, ...this.options.env } : process.env,
	stdio: ["ignore", "pipe", "pipe"],
});
```
`packages/coding-agent/src/core/kernel/index.ts:647-651`

Три канала, connection-файл с HMAC-ключом и правами 0600:

```ts
this.shell = new Dealer();
this.iopub = new Subscriber();
this.control = new Dealer();
this.shell.connect(`${conn.transport}://${conn.ip}:${conn.shell_port}`);
this.iopub.connect(`${conn.transport}://${conn.ip}:${conn.iopub_port}`);
this.control.connect(`${conn.transport}://${conn.ip}:${conn.control_port}`);
```
`packages/coding-agent/src/core/kernel/index.ts:690-695`

```ts
writeFileSync(path, JSON.stringify(info, null, 2), { mode: 0o600 });
```
`packages/coding-agent/src/core/kernel/index.ts:466`

Есть fast-path: форк-сервер с предимпортированным ядром, деградирует до прямого спавна при любой
ошибке — «correctness never depends on fork» (`core/kernel/fork-server.ts:1-8`, вызов на
`core/kernel/index.ts:617-644`). Форкнутое ядро — не прямой ребёнок, поэтому его смерть ловят
поллингом pid раз в секунду (`FORKED_LIVENESS_POLL_MS = 1000`, `core/kernel/index.ts:35,718-728`).

### Связь процесса с сессией агента

Ядро создаётся лениво, по одному на сессию, владелец — `IpythonKernelProvisioner`
(`core/tools/ipython.ts:322-345`). Порядок старта задан явно и важен:

```ts
await withKernelBootPermit(() => { ... return m.start({...}); }, startupSignal);
// Revive a prior session's namespace before the bootstrap, so the bootstrap
// then overwrites live handles (rlm, skills) on top of anything restored.
if (snapshotDir) { ... const restore = await raceWithAbort(m.restoreState(), startupSignal); ... }
this.emitStartupProgress("Preparing IPython runtime...");
const bootstrap = await m.execute(buildRlmBootstrapCode(this.options?.pythonSkills), {...});
```
`packages/coding-agent/src/core/tools/ipython.ts:500-521`

Bootstrap-код кладёт в namespace `rlm` и импортирует Python-скиллы
(`core/tools/ipython.ts:24-68` и `:70-141`).

### Переменные между ходами

Namespace живёт в процессе ядра и переживает ходы и компакцию (ядро не перезапускается между
ходами вообще). Между *перезапусками* — восстанавливается из dill-снапшота, см. §2.
Явно ломает состояние только принудительный kill зависшей ячейки, и модели об этом говорят
отдельным блоком:

```ts
const KERNEL_RESTART_NOTICE = [
	"<ipython_kernel_reset>",
	"The IPython kernel was restarted after a previous interrupted cell kept running. Variables, imports, async tasks, and open resources from before the restart are no longer available; recreate them before using them.",
	"</ipython_kernel_reset>",
].join("\n");
```
`packages/coding-agent/src/core/tools/ipython.ts:157-161`

`%%bash`-ячейка — временный сабшелл, а `%cd` и Python-состояние остаются
(`docs/rlm.md:51`); `%%bash` может переписываться в `%%script <shell>` при заданном `shellPath`
(`core/tools/ipython.ts:303-320`).

### Таймаут на выполнение кода — ЕГО НЕТ

В `executeInner` нет ни одного wall-clock таймера на саму ячейку. Все константы-таймауты в файле
относятся к старту и завершению:

```ts
const PORTS_RESOLVE_TIMEOUT_MS = 5000;
const READY_TIMEOUT_MS = 5000;
const HOST_REQUEST_DISPOSE_TIMEOUT_MS = 5000;
const SNAPSHOT_DISPOSE_TIMEOUT_MS = 5000;
const KERNEL_ABORT_GRACE_MS = 1000;
```
`packages/coding-agent/src/core/kernel/index.ts:27-42`

Единственный способ остановить ячейку — внешний `AbortSignal` (Ctrl+C / отмена хода), и он даёт
ядру 1 секунду на реакцию, после чего исполнение помечается `aborted` — но код в ядре продолжает
крутиться:

```ts
const onAbort = () => {
	void this.interrupt().catch(() => undefined);
	clearAbortTimer();
	abortTimer = globalThis.setTimeout(forceAbort, KERNEL_ABORT_GRACE_MS);
```
`packages/coding-agent/src/core/kernel/index.ts:905-908`

Именно поэтому следующий вызов может упереться в `KernelBusyAfterInterruptError` и пользователю
предлагают выбор «ждать / убить ядро» (`core/tools/ipython.ts:150-156`, `:547-609`).
Без UI (`ctx.hasUI === false`) выбора нет — возвращается `cancel` (`core/tools/ipython.ts:551-553`).

**Вывод по §1:** бесконечный цикл в сгенерированном коде ничем не ограничен по времени;
защита только ручная (Ctrl+C) или через таймаут провайдера/пользователя выше по стеку.

---

## 2. Падение ядра и восстановление

Заявка блога: «recoverable worker process; if a worker crashes, the daemon recovers it from the
session JSONL and kernel state snapshot». **Оба механизма в коде есть, но это два независимых
механизма**, и «kernel state snapshot» устроен слабее, чем звучит.

### Что именно снапшотится

Файл `packages/coding-agent/src/core/kernel/state-snapshot.ts` целиком про это. Заголовок файла
честно описывает подход:

```ts
// Snapshotting is best-effort and per-variable: each top-level name is pickled
// with `dill` independently, so a single unpicklable object (open file, socket,
// GPU tensor, …) is skipped and reported rather than aborting the whole snapshot.
```
`packages/coding-agent/src/core/kernel/state-snapshot.ts:5-7`

Сериализация — `dill`, по одному имени верхнего уровня:

```python
    always_skip = {"rlm", "asyncio", "In", "Out", "get_ipython", "exit", "quit", "open"}
    ...
    for name in _b.list(ns.keys()):
        if name.startswith("_") or name in hidden or name in always_skip:
            continue
        value = ns[name]
        # Modules are pickled by reference and re-imported on restore.
        try:
            blob = dill.dumps(value)
        except _b.Exception as _err:
            skipped.append({"name": name, "reason": _b.type(_err).__name__ + ": " + _b.str(_err)[:200]})
            continue
```
`packages/coding-agent/src/core/kernel/state-snapshot.ts:78-95`

**Непиклящиеся объекты просто выбрасываются** с записью причины в `skipped`. Никакого fallback
(repr, отложенная реконструкция) нет.

Лимит размера:

```ts
/** Default ceiling on a snapshot payload. Over-cap variables are skipped + reported. */
export const DEFAULT_SNAPSHOT_MAX_BYTES = 256 * 1024 * 1024;
```
`packages/coding-agent/src/core/kernel/state-snapshot.ts:10-11`

```python
        if _b.len(blob) > ${maxBytes} or total + _b.len(blob) > ${maxBytes}:
            skipped.append({"name": name, "reason": "exceeds snapshot size cap"})
            continue
```
`packages/coding-agent/src/core/kernel/state-snapshot.ts:96-98`

Запись атомарная (`.tmp` + `os.replace`), рядом кладётся JSON-манифест со списком сохранённых имён,
причинами пропуска, размером, версией Python и timestamp
(`state-snapshot.ts:102-131`). Файлы: `kernel-state.dill` и `kernel-state.json` в
`session-artifacts/<session-id>/` (`state-snapshot.ts:37-45`, `docs/rlm-runtime.md:237-238`).

### Периодичность

Снапшот дебаунсится на 1.5 с и берётся **только после успешной ячейки**:

```ts
const DEFAULT_SNAPSHOT_DEBOUNCE_MS = 1500;
```
`packages/coding-agent/src/core/kernel/index.ts:33`

```ts
	async execute(code: string, opts: ExecuteOptions = {}): Promise<ExecuteResult> {
		const result = await this.enqueueExecute(code, opts);
		// Refresh the on-disk snapshot after real work so a later resume (or a
		// crash before graceful shutdown) revives the most recent namespace.
		if (result.status === "ok") {
			this.scheduleSnapshot();
		}
		return result;
	}
```
`packages/coding-agent/src/core/kernel/index.ts:803-811`

Плюс финальный flush при graceful dispose, ограниченный 5 секундами
(`core/kernel/index.ts:1484-1497`, вызывается первым делом в `dispose()`, `:1500-1503`).

### Что теряется при падении

1. Всё, что не пиклится (`skipped`) — навсегда: открытые файлы, сокеты, соединения, лямбды с
   незапикливаемыми замыканиями, живые asyncio-таски.
2. Всё, что изменилось за последние ≤1.5 с после успешной ячейки (окно дебаунса).
3. Всё, что произвела **упавшая** ячейка (`status !== "ok"` → снапшот не планируется).
4. Имена с ведущим `_`, `In`/`Out`, `rlm`, `asyncio` — по дизайну (`state-snapshot.ts:78,87`).

### Восстановление

Restore тоже best-effort, по имени, и никогда не бросает:

```python
    for name, blob in payload.items():
        try:
            ns[name] = dill.loads(blob)
            restored.append(name)
        except _b.Exception as _err:
            failed.append({"name": name, "reason": _b.type(_err).__name__ + ": " + _b.str(_err)[:200]})
```
`packages/coding-agent/src/core/kernel/state-snapshot.ts:180-185`

Результат восстановления сообщается модели, и только после успешного bootstrap:

```ts
// Only tell the model what was revived once the kernel is actually usable —
// a notice claiming restored state must never outlive a failed bootstrap.
if (pendingRestore) {
	this._lastRestore = pendingRestore;
	this.options?.onRestore?.(pendingRestore);
}
```
`packages/coding-agent/src/core/tools/ipython.ts:531-536`

### Recovery воркера — это отдельный, другой механизм

Демон-супервизор перезапускает воркер по фиксированной лесенке ретраев:

```ts
const WORKER_RETRY_DELAYS_MS = [250, 1000, 5000] as const;
```
`packages/coding-agent/src/modes/daemon/daemon-supervisor.ts:136`

`recoverWorker()` (`daemon-supervisor.ts:2706-2800`) сначала пробует переподключиться к живому
процессу (сверяя `processStartId`, чтобы не адоптировать чужой переиспользованный pid), и только
затем убивает и перезапускает.

**В журнале восстановления НЕТ ничего про ядро** — только идентичность сессии и флаг «был занят»:

```ts
export interface WorkerRecoveryRecord {
	version: 1;
	activeSessionId: string;
	sessionId: string;
	sessionFile?: string;
	busy: boolean;
	operation: string;
	recordedAt: string;
}
```
`packages/coding-agent/src/modes/daemon/worker-recovery-journal.ts:14-22`

Незавершённые операции помечаются как interrupted и **не переигрываются**:

```ts
		const uncertain = latest.filter((record) => record.busy);
		...
			await Promise.all([...interruptedSessions.values()].map((interrupted) =>
				this.catalog.markInterrupted(interrupted.sessionFile, interrupted.activeSessionId, [...interrupted.operations]),
			));
```
`packages/coding-agent/src/modes/daemon/daemon-supervisor.ts:2851-2862` и `:2821-2830` (перед этим
`signalProcessGroupOrProcess(worker.descriptor.pid, "SIGKILL")` и отстрел осиротевших detached-процессов
по `orphanProcessJournalPath`).

Документация формулирует то же самое: «Workers journal operation transitions and detached subprocess
identities. After a worker crash, recovery reaps its old process group and tracked detached bash
trees, appends a visible recovery marker to the transcript, restores the root under the same
active-session ID, and does not replay uncertain side effects» (`docs/daemon.md:142`).

**Итог по §2:** заявка верна, но с существенным уточнением — «kernel state snapshot» это
дебаунсенный dill-дамп верхнего уровня namespace с молчаливой (хотя и отчитываемой) потерей всего
непиклящегося, а не снимок процесса. Демон восстанавливает *сессию*, а ядро при этом стартует
заново и подтягивает то, что смогло пережить pickle.

---

## 3. Субагенты

### Как спавнится

Python-сторона — тонкий шим, вся работа у хоста:

```python
async def run(prompt: str, **kwargs: Any) -> RLMSpawnHandle:
    """Spawn a recursive Prime Agent child and return once its task is admitted."""
    if not isinstance(prompt, str):
        raise TypeError(f"prompt must be str, got {type(prompt).__name__}")
    payload = await host_request("rlm.run", {"prompt": prompt, "kwargs": kwargs})
    return _spawn_handle_from_payload(payload)
```
`prime-agent-runtime/src/rlm/__init__.py:143-151`

Транспорт — Jupyter comm с таргетом `host.request`, ответ приходит **по control-каналу**:

```python
HOST_COMM_TARGET = "host.request"
...
def _install_control_comm_handlers() -> None:
    """Let comm replies arrive on the control channel during an execute_request."""
    ...
    control_handlers.setdefault("comm_msg", comm_manager.comm_msg)
    control_handlers.setdefault("comm_close", comm_manager.comm_close)
```
`prime-agent-runtime/src/rlm/__init__.py:24,53-64`

Причина именно такая, как ожидаешь: shell-канал в IPython последователен, и ответ по нему
залочил бы ту же ячейку, которая его ждёт — «Sending the admission response on the shell channel
would deadlock» (`docs/rlm-runtime.md:121`).

**Отдельного процесса на субагента нет.** Ребёнок — обычный `AgentSession` внутри того же
воркер-процесса: «Each worker owns one root `AgentSessionRuntime`, its root `AgentSession`,
scheduler, kernels, and every RLM descendant below that root» (`docs/daemon.md:27`).
У ребёнка свой контекст, свой каталог сессии и свой IPython-kernel.

Возврат — только handle, никогда не ответ:

```python
@dataclass(frozen=True)
class RLMSpawnHandle:
    rlm_child_id: str
    name: str
    session_dir: Path
    model: str
```
`prime-agent-runtime/src/rlm/__init__.py:27-32`

Это breaking change 0.6.0: «Changed `rlm(...)` to return at task admission instead of waiting for
the child to finish» (`packages/coding-agent/CHANGELOG.md:33`).

### Валидация и лимит рекурсии

```ts
const { name: rawName, model: rawModel, ...unsupported } = kwargs;
const unsupportedKwargs = Object.keys(unsupported);
if (unsupportedKwargs.length > 0) {
	throw new Error(`Unsupported rlm.run kwargs: ${unsupportedKwargs.sort().join(", ")}`);
}
...
if (this._rlmDepth >= this._rlmMaxDepth) {
	throw new Error(
		`RLM recursion depth limit reached (RLM_DEPTH=${this._rlmDepth}, RLM_MAX_DEPTH=${this._rlmMaxDepth})`,
	);
}
```
`packages/coding-agent/src/core/agent-session.ts:9589-9601`

Дефолт глубины — 1 (корень может создавать детей, дети — нет), источник разрешается по цепочке
chat → inherited → global → env → default:

```ts
	return { maxDepth: 1, source: "default" };
```
`packages/coding-agent/src/core/agent-session.ts:1591` (вся цепочка `:1573-1591`)

Имя ограничено 64 символами (`core/rlm-runtime.ts:57,73-75`), при отсутствии — генерируется
`subagent-<slug>-<id8>` (`core/rlm-runtime.ts:95-112`).

### «Nuclear family» в коде

Это ограничение **адресации сообщений/наблюдения**, а не спавна. Чистая функция политики:

```ts
/** Pure nuclear-family policy over persisted parent-edge snapshots. */
export function agentFamilyRelationship(
	current: AgentFamilyCatalogEntry,
	target: AgentFamilyCatalogEntry,
): AgentFamilyRelationship | undefined {
	if (current.id === target.id) return undefined;
	if (isAgentFamilyParent(target, current)) return "parent";
	if (isAgentFamilyParent(current, target)) return "child";
	if (current.depth === target.depth && sameAgentFamilyParent(current, target, [current, target])) return "sibling";
	return undefined;
}

export function assertAgentFamilyReach(...): AgentFamilyRelationship {
	const relationship = agentFamilyRelationship(current, target);
	if (!relationship) throw new Error(AGENT_FAMILY_REACH_ERROR);
	return relationship;
}
```
`packages/coding-agent/src/core/agent-messages.ts:309-327`

Смысл в CHANGELOG: «an agent may message or observe only its parent, siblings, and direct children.
Top-level sessions are siblings of one another... grandchildren and cousins must be reached by
relaying through the intermediate child» (`packages/coding-agent/CHANGELOG.md:36`).

Броадкаст запрещён явно:

```ts
	if (normalized === "*" || normalized.toLowerCase() === "all" || normalized.toLowerCase() === "broadcast") {
		throw new Error("Broadcast agent messaging is not supported");
	}
```
`packages/coding-agent/src/core/agent-messages.ts:350-352`

И есть лимит очереди на сессию (`assertAgentMessageQueueCapacity`, `agent-messages.ts:356-368`) и
лимит длины сообщения (`normalizeAgentSessionMessage`, `:333-343`).

### Где живёт реестр

Append-only JSONL на родителя, с `fsync` на каждой записи:

```ts
const RLM_SUBAGENT_REGISTRY_FILE = "rlm-subagents.jsonl";
```
`packages/coding-agent/src/modes/daemon/daemon-mode.ts:375`

```ts
			const handle = openSync(path, "a");
			try {
				writeSync(handle, `${separator}${JSON.stringify(entry)}\n`);
				fsyncSync(handle);
			} finally {
				closeSync(handle);
			}
```
`packages/coding-agent/src/modes/daemon/daemon-mode.ts:900-906`

Удаление — не удаление строки, а дописывание записи со `status: "deleted"`
(`daemon-mode.ts:954-968`); чтение — «последняя запись по childId выигрывает»
(`readLatestRlmSubagentRegistry`, `daemon-mode.ts:972-1000`). Путь для чужого процесса-каталога:
`join(dirname(dirname(parent.path)), "session-artifacts", parent.id, "rlm-subagents.jsonl")`
(`modes/daemon/daemon-catalog-process.ts:76`).

Подсказка про `test_subagent_registry.py` уводит немного не туда: питоновский тест
(`prime-agent-runtime/test/test_subagent_registry.py`, 225 строк) проверяет только валидацию
шима — что `list_subagents()` корректно разбирает ответ хоста и что мусорный payload отвергается.
Настоящий реестр целиком в TS.

### Выгрузка из памяти и восстановление

**Заявленных «30 минут» в коде нет.** Дефолт — 90 минут, и это глобальная настройка:

```ts
export const DEFAULT_IDLE_EVICTION_MINUTES = 90;
```
`packages/coding-agent/src/core/settings-manager.ts:9`

```ts
	idleEvictionMinutes?: number | "off"; // global daemon policy; default: 90
```
`packages/coding-agent/src/core/settings-manager.ts:131`

Порог считается от последней активности:

```ts
		now - session.lastActivityAt >= idleEvictionMinutes * 60_000
```
`packages/coding-agent/src/core/session-action-store.ts:351`

В UI выбор из `[30, 60, 90, 180, 360]` + `off` (`modes/interactive/components/settings-selector.ts:206,225`),
так что 30 минут — это одно из значений, но не дефолт.

Пассивация применима только к субагентам и требует резидентного родителя:

```ts
		if (!sessionFile || metadata.kind !== "subagent" || !metadata.rlmChildId || !metadata.parentActiveSessionId) {
			return false;
		}
```
`packages/coding-agent/src/modes/daemon/daemon-mode.ts:2466-2468`

```ts
			// Detach parent tracking before the standard graceful runtime disposal. The
			// registry/catalog rows remain the sole passive representation after close.
			const unsubscribeChild = parentState.runtime.session.releaseRlmChildSession(childId, state.runtime.session);
```
`packages/coding-agent/src/modes/daemon/daemon-mode.ts:2497-2499`

Обратно поднимается лениво — `hydratePassiveRlmSubagent` (`daemon-mode.ts:2566-2620`), с явной
ошибкой при мёртвом родителе: «Cannot hydrate RLM subagent … without a resident root parent»
(`daemon-mode.ts:2592`). Дока подтверждает: «This registry survives kernel restart, compaction, and
parent restore. Successfully completed daemon-backed children are rehydrated from the parent
artifact registry. Inline children remain inspectable in the current process but have no
active-session ID» (`docs/rlm-runtime.md:189`).

За один свип пассивируется не больше двух детей на воркер (`CHILD_PASSIVATION_PER_WORKER_CAP = 2`,
`daemon-supervisor.ts:143`).

---

## 4. Continual Harness / самоизменение

### Где физически лежит H = (ρ, G, K, M)

Один JSON-файл на скоуп, четыре типа записей:

```python
HarnessKind = Literal["prompt", "memory", "skill", "subagent"]
HarnessScope = Literal["local", "global"]

_DEFAULT_FILE_NAME = "harness_state.json"
_DEFAULT_HARNESS_DIR_NAME = "harness"
_KINDS: tuple[HarnessKind, ...] = ("prompt", "memory", "skill", "subagent")
```
`prime-agent-runtime/src/rlm/harness.py:18-23`

Разрешение пути: локальный скоуп требует `RLM_HARNESS_STATE_DIR` или `RLM_SESSION_DIR`, глобальный
падает в `~/.prime/agent/harness/`:

```python
    if root is None and not global_ and (session_dir := _env_dir("RLM_SESSION_DIR")):
        root = Path(session_dir) / _DEFAULT_HARNESS_DIR_NAME
    if root is None and not global_:
        raise RuntimeError(
            "Local harness state requires RLM_HARNESS_STATE_DIR or RLM_SESSION_DIR. "
            "Use get_harness_state(global_=True) for global state."
        )
```
`prime-agent-runtime/src/rlm/harness.py:81-87`

Запись:

```python
@dataclass
class HarnessEntry:
    id: str
    kind: HarnessKind
    title: str
    content: str
    path: str = "general"
    scope: HarnessScope = "local"
    reference: dict[str, Any] = field(default_factory=dict)
    arguments: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = "agent"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    version: int = 1
```
`prime-agent-runtime/src/rlm/harness.py:93-109`

Дока: «Session-local state lives in the session artifact directory under `harness/harness_state.json`.
Explicitly global entries live under `~/.prime/agent/harness/`» (`docs/rlm-runtime.md:211`).

### Как попадает в системный промпт

```ts
		if (harnessState) {
			prompt += `\n\n${formatHarnessStateForPrompt(harnessState, { includeIpythonExamples: hasIpython, includeShellExamples: hasBash, includeRefineExamples: hasIpython && hasRefineSkill })}`;
		}
```
`packages/coding-agent/src/core/system-prompt.ts:105-106` (и второй путь `:140-141`)

Блок **дописывается в конец**, после базового промпта:

```ts
	// Appended AFTER the trained buildRlmPrompt prefix, and before the harness-state
```
`packages/coding-agent/src/core/system-prompt.ts:126`

### ГЛАВНОЕ: гардрейлы

**(а) Иммутабельность базового промпта форсится в одном месте и очень узко:**

```ts
	if (edit.kind === "prompt" && (edit.id === "base_system_prompt" || computedId === "base_system_prompt")) {
		return "base system prompt is not editable";
	}
```
`packages/coding-agent/src/core/refinement/refinement.ts:671-673`

То есть настоящая иммутабельность — **структурная, а не проверочная**: harness-записи физически
не могут переписать базовый текст, потому что рендерятся отдельным блоком поверх него
(`system-prompt.ts:105-106`). Проверка на `base_system_prompt` — просто запрет на entry с таким id.
Это же повторяют инструкции: «prompt: supplemental prompt notes only. The base system prompt is
immutable and MUST NOT be rewritten» (`refinement/refinement.ts:135`) и текст, уходящий в промпт:
«The base system prompt is immutable; prompt entries below are supplemental notes only»
(`refinement/refinement.ts:451`).

**(б) Валидация правок — есть, полная функция `validateEdit`** (`refinement.ts:664-704`):
белый список действий и типов, `update`/`delete` требуют id, `create`/`update` требуют title+content,
skill дополнительно требует `arguments` и `reference` с `type: "python"`, импортом и callable.
Питоновская сторона валидирует то же для скиллов (`harness.py:128-138`).

**(в) Лимита на размер контента или число записей в хранилище — НЕТ.** Ни в `HarnessState.upsert`
(`harness.py:302-342`), ни в `_upsert` (`:344-400`), ни в `save()` (`:284-300`) нет проверок длины
`content` или количества записей. Единственная нормализация — `_slug(...)[:80]` для id
(`harness.py:31-34`).

**Ограничен не store, а промпт.** Именно это и есть работающий гардрейл против раздувания контекста:

```ts
const DEFAULT_OVERVIEW_ENTRY_LIMIT = 6;
const DEFAULT_OVERVIEW_REFINEMENT_LIMIT = 5;
const DEFAULT_OVERVIEW_CONTENT_LIMIT = 180;
```
`packages/coding-agent/src/core/refinement/refinement.ts:26-28`

В промпт уходит максимум 6 записей каждого вида, по 180 символов, плюс `- +N more <kind> entries`
(`refinement.ts:494-508`). В питоновском `overview()` лимит другой — 20 записей и 120 символов
(`harness.py:721,740-742`).

**(г) Откат по ID — РЕАЛИЗОВАН, но только для правок, прошедших через `/refine`.**

Каждая применённая правка сохраняет `before` и `after`:

```ts
		const before = cloneEntry(records[id]);
		...
		appliedEdits.push({ ...edit, id, before, after: cloneEntry(after), applied: true });
```
`packages/coding-agent/src/core/refinement/refinement.ts:723,775`

Откат строится инверсией этого списка в обратном порядке:

```ts
function rollbackProposal(target: RefinementResult): RefinementProposal {
	const edits: RefinementEdit[] = [];
	for (const edit of [...target.appliedEdits].reverse()) {
		if (!edit.applied) continue;
		if (edit.before) {
			edits.push({ action: edit.after ? "update" : "create", kind: edit.kind, id: edit.id, title: edit.before.title, ... });
		} else if (edit.after) {
			edits.push({ action: "delete", kind: edit.kind, id: edit.id, reason: `Rollback ${target.id}` });
		}
	}
```
`packages/coding-agent/src/core/refinement/refinement.ts:804-822`

Точка входа — `/refine rollback <refinement-id>`:

```ts
	if (rest === "rollback") throw new Error("Usage: /refine rollback <refinement-id>");
```
`packages/coding-agent/src/core/slash-commands.ts:42`

```ts
	if (options.rollbackId) {
		const target = history.find((item) => item.id === options.rollbackId);
		if (!target) throw new Error(`Refinement ${options.rollbackId} not found`);
```
`packages/coding-agent/src/core/refinement/refinement.ts:878-881`

История локальных рефайнментов лежит в session JSONL как custom-записи типа
`prime-agent.refinement` (`refinement.ts:21`, `getRefinementHistory` `:838-846`), глобальных —
в `refinements.jsonl` (`refinement.ts:25`, `appendGlobalRefinement` `:374-379`), с явным
комментарием про устойчивость: «Skip malformed lines so a single bad append cannot break rollback»
(`refinement.ts:396`).

**Дыра, которую стоит держать в голове:** прямые вызовы из ядра
(`rlm.harness.update_memory(...)`, `delete_prompt_note(...)` и т.д., рекламируемые прямо в
системном промпте, `core/prompts/rlm.ts:29`) идут мимо этого пути. `HarnessState._upsert`
инкрементит `version`, но **старый контент не сохраняет** (`harness.py:366-384`) — предыдущая
редакция затирается на диске. Откатить такую правку нечем: `before` нигде не записан.
Откат «by ID» покрывает только `/refine`-транзакции.

**(д) Защита от одновременной записи хостом и ядром — есть:**

```python
    def _sync_from_disk(self) -> None:
        """Reload if another process rewrote the state file since we last touched it.
        ... Without this guard the next in-kernel ``save()`` would overwrite host edits with a
        stale snapshot.
        """
        if self._disk_mtime() != self._loaded_mtime:
            self.load()
```
`prime-agent-runtime/src/rlm/harness.py:186-196`

И симметрично на стороне `/refine` — оптимистичная блокировка по baseline:

```ts
		if (options.baselineState && !proposalModifiedKeys.has(entryKey) && JSON.stringify(before) !== JSON.stringify(baseline)) {
			appliedEdits.push({ ...edit, id, before, applied: false, error: "entry changed during refinement planning" });
			continue;
		}
```
`packages/coding-agent/src/core/refinement/refinement.ts:726-737`

**(е) Fail-soft на битом состоянии:** повреждённый JSON не роняет ядро, трактуется как пустой
(`harness.py:206-213`); резолвинг harness-состояния обёрнут так, чтобы никогда не бросать внутри
namespace ядра (`__init__.py:233-272`, комментарий: «harness access must never raise»).

### Что меняет `/refine`

Отдельный LLM-проход со своим системным промптом (`refinement.ts:123-166`), который выдаёт строгий
JSON `{summary, rationale, expectedOutcome, edits[]}`; каждый edit — `create|update|delete` над
одним из четырёх видов. Бюджет вывода привязан к модели, а не к константе:

```ts
const REFINEMENT_MAX_OUTPUT_TOKENS = 32_000;
...
function refinementMaxOutputTokens(model: Model<any>): number {
	return Math.min(model.maxTokens, REFINEMENT_MAX_OUTPUT_TOKENS);
```
`packages/coding-agent/src/core/refinement/refinement.ts:186,199-201`

Есть авто-режим с гейтом-ревьюером (`AUTO_REFINE_REVIEW_SYSTEM_PROMPT`, `refinement.ts:175-186`),
триггеры — `"turn_interval" | "compact"` (`refinement.ts:108`). Для модели `refine.run()` описан как
fire-and-forget: «It returns immediately and runs when the current turn ends»
(`core/prompts/rlm.ts:158`).

---

## 5. Цена REPL как единственного интерфейса

### Ошибки исполнения

Traceback склеивается в текст тул-результата, ошибка помечается как ошибка тула:

```ts
				let text = r.stdout;
				if (r.stderr) text += (text ? "\n" : "") + r.stderr;
				if (r.result) text += (text ? "\n" : "") + r.result;
				if (r.status === "error" && r.error) {
					text += (text ? "\n" : "") + r.error.traceback.join("\n");
				}
```
`packages/coding-agent/src/core/tools/ipython.ts:667-672`

```ts
					isError: r.status === "error" || r.status === "aborted",
```
`packages/coding-agent/src/core/tools/ipython.ts:695`

`stop_on_error: true` в `execute_request` (`core/kernel/index.ts:858`) — многострочная ячейка
обрывается на первой ошибке. Структурированные детали (`ename`, `evalue`, `traceback`,
`durationMs`) уходят в `details` для UI (`ipython.ts:682-694`).

### Песочница — ЕЁ НЕТ, и это заявлено явно

```
The IPython kernel runs model-generated Python and project commands with the worker's operating-system
permissions. It is a durable control environment, not a security sandbox. Review third-party Python
skills and use an external sandbox or restricted environment for untrusted repositories and instructions.
```
`packages/coding-agent/docs/rlm.md:143`

То же в трёх других местах: `docs/rlm-runtime.md:251`, `docs/architecture.md:49`,
`docs/daemon.md:120` («It is process coordination, not a sandbox boundary: all processes still run
as the same OS user»), `README.md:66`.

В коде подтверждается отсутствием какого-либо слоя разрешений: тул `ipython` не спрашивает
подтверждения ни на что, единственный интерактивный вопрос за всё время жизни ядра — что делать с
зависшей ячейкой (`core/tools/ipython.ts:547-564`). Поиск по `sandbox` в `src/` даёт только
`restore-sandbox-env.ts` — восстановление `process.env` под Bun внутри чужой песочницы
(`src/bun/restore-sandbox-env.ts:5-15`), то есть про чужую изоляцию, не про свою.

### Секреты в namespace

Две конкретные проблемы, обе следуют из механики, а не из бага:

1. **Снапшот пиклит весь namespace на диск.** Любой токен, присвоенный переменной верхнего уровня,
   попадает в `kernel-state.dill`. Явного ограничения прав на этот файл нет: Python пишет его
   обычным `open(tmp, "wb")` и `os.makedirs(...)` без `mode`
   (`core/kernel/state-snapshot.ts:102-107`). Для сравнения — connection-файл с HMAC-ключом права
   выставляет явно: `writeFileSync(path, ..., { mode: 0o600 })` (`core/kernel/index.ts:466`).
   Фильтрации имён по признаку «похоже на секрет» в `always_skip` нет
   (`state-snapshot.ts:78`) — там только служебные имена.

2. **`auth.json` читается прямо из ядра.** Не через хост, а файлом:

```python
def _read_auth(provider: str) -> dict[str, Any] | None:
    """Read one credential entry from auth.json. Returns None if absent/unreadable."""
    try:
        data = json.loads((_agent_dir() / "auth.json").read_text())
```
`prime-agent-runtime/src/rlm/mcp_base.py:68-71`

   То есть любой сгенерированный моделью код в ячейке может прочитать все креды всех интеграций
   одной строкой. Частично это осознано — `!command`-индирекция в конфиге намеренно не резолвится
   в ядре: «The command form can't run safely in the kernel (the host injects those resolved), so
   skip it» (`mcp_base.py:84-89`).

### Лимиты вывода

```ts
const DEFAULT_MAX_OUTPUT_CHARS = 65536;
```
`packages/coding-agent/src/core/kernel/index.ts:31`

```ts
			if (execution.stdoutTruncated) stdout += `\n[... output truncated at ${execution.maxChars} chars ...]`;
			if (execution.stderrTruncated) stderr += `\n[... output truncated at ${execution.maxChars} chars ...]`;
```
`packages/coding-agent/src/core/kernel/index.ts:1067-1068`

Отдельно — потолок на одно вложение (изображение) и лимит поздних agent-message-хендлеров:

```ts
const MAX_LATE_SENT_AGENT_MESSAGE_HANDLERS = 256;
```
`packages/coding-agent/src/core/kernel/index.ts:44`

При компакции результаты тулов режутся ещё жёстче: «Tool results are truncated to 2000 characters
during serialization... since tool results, especially from `ipython` and optional `bash`, are
typically the largest contributors to context size» (`docs/compaction.md:268`).

### TODO / известные проблемы

Самое красноречивое — первые строки обоих ключевых файлов:

```ts
// TODO: reconsider persistent kernel vs stateless `python -c` once RLM-1 weights land.
```
`packages/coding-agent/src/core/kernel/index.ts:1`

```ts
// TODO: reconsider whether the persistent kernel is needed once RLM-1 weights land.
```
`packages/coding-agent/src/core/tools/ipython.ts:1`

Они сами держат persistent-ядро как временное решение до собственных весов.

Остальные TODO в этой области:

```ts
			// TODO: plumb AbortSignal through AgentSession.prompt so disposal can cancel long-running child loops.
```
`packages/coding-agent/src/core/kernel/index.ts:1507` — при dispose родителя долгие детские циклы
отменить нечем, ждут по таймауту `HOST_REQUEST_DISPOSE_TIMEOUT_MS = 5000`.

```ts
		// TODO: replace this best-effort hard-exit path if Node exposes an awaitable process-exit cleanup hook.
```
`packages/coding-agent/src/core/kernel/index.ts:1522` — на `process.on('exit')` снапшот сделать
уже нельзя, `disposeSync()` только чистит ресурсы.

**GitHub issues проверить не удалось: `gh` в этом окружении не установлен** (`which gh` → exit 1),
сетевого доступа к API я не запрашивал. Косвенно закрытые issues видны в CHANGELOG:
#617, #620, #621, #622, #623 (`packages/coding-agent/CHANGELOG.md:22-29`) — все про демон/ACP/CLI,
не про ядро.

---

## 6. MCP — как прокидывается в REPL

**Ключевое для нас: MCP-тулы НЕ становятся тулами модели.** Ни одним.

```
Consistent with Prime Agent's single-tool design, MCP integrations are **not**
exposed as new agent tools. Each integration is a [Python-backed skill](skills.md)
that the model imports and calls from the IPython kernel:

```python
import linear
issues = await linear.list_issues(team="Engineering")
```

The MCP connection runs inside the kernel via the official `mcp` Python SDK. The
host's only jobs are interactive login (browser OAuth) and minting/refreshing
credentials in `auth.json`.
```
`packages/coding-agent/docs/mcp-integrations.md:6-17`

### Механика

Базовый класс, от которого наследуется интеграция-скилл:

```python
class McpIntegration:
    """Subclass and set :attr:`server` (and :attr:`url` for remote servers).

    Tools are discovered on first use and bound as async methods via
    ``__getattr__``; ``await self.call_tool(name, args)`` is the explicit escape
    hatch and the hook for hand-written typed wrappers.
    """
```
`prime-agent-runtime/src/rlm/mcp_base.py:112-118`

Тулы биндятся динамически, без кодогенерации:

```python
    def __getattr__(self, name: str):
        # Only reached for names not found normally; bind as an async tool call.
        if name.startswith("_"):
            raise AttributeError(name)

        async def _call(**kwargs: Any) -> Any:
            await self._ensure_tools()
            if self._tools is not None and name not in self._tools:
                available = ", ".join(sorted(self._tools)) or "(none)"
                raise AttributeError(f"'{self.server}' has no tool '{name}'. Available: {available}")
            return await self.call_tool(name, kwargs)
```
`prime-agent-runtime/src/rlm/mcp_base.py:283-295`

JSON Schema тула становится docstring'ом Python-функции — то есть модель узнаёт схему через
`help()`, а не через промпт:

```python
        if self._tools and name in self._tools:
            schema = self._tools[name].get("inputSchema") or {}
            desc = self._tools[name].get("description") or ""
            _call.__doc__ = f"{desc}\n\nArguments (JSON Schema):\n{json.dumps(schema, indent=2)}"
```
`prime-agent-runtime/src/rlm/mcp_base.py:299-302`

**Сессия открывается заново на каждый вызов** — и это осознанно, ровно из-за снапшота ядра:

```python
    async def call_tool(self, tool: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call ``tool`` on the server and return its parsed result.

        Opens a fresh session per call: MCP sessions are not safe to hold across
        the kernel's snapshot/restore, and per-call connect keeps this robust to
        idle sessions and token rotation at modest latency cost.
        """
        async with AsyncExitStack() as stack:
            session = await self._open_session(stack)
            result = await session.call_tool(tool, arguments or {})
        return _parse_result(result)
```
`prime-agent-runtime/src/rlm/mcp_base.py:271-281`

### Транспорт и авторизация

Дефолтный транспорт — **только remote streamable HTTP** с Bearer-токеном:

```python
    async def _open_session(self, stack: AsyncExitStack):
        """Open an initialized MCP ClientSession bound to ``stack``.

        Override for non-HTTP transports (e.g. stdio). The default connects over
        streamable HTTP with a Bearer token from auth.json.
```
`prime-agent-runtime/src/rlm/mcp_base.py:206-211`

Для stdio-серверов (как у нас в Orchestra) готового пути нет — нужно переопределять
`_open_session` в своём Python-пакете скилла.

Токен: env-переменная `bearer_token_env` побеждает, иначе `auth.json`, OAuth-токен отдаётся только
пока свежий с запасом 30 секунд:

```python
_EXPIRY_SKEW_SECONDS = 30
...
        fresh = isinstance(expires, (int, float)) and (
            time.time() * 1000 < expires - _EXPIRY_SKEW_SECONDS * 1000
        )
        if access and fresh:
            return access
        return None  # signal: needs refresh
```
`prime-agent-runtime/src/rlm/mcp_base.py:33,160-165`

Рефреш — единственное, что уходит на хост (`host_request("mcp.refresh", ...)`, `mcp_base.py:176`),
как и резолвинг URL/заголовков с учётом пользовательского `mcpServers`-оверрайда
(`host_request("mcp.config", ...)`, `mcp_base.py:196`). Интерактивный логин — только host-side.

Различаются два состояния отказа, и это сделано специально:

```python
            # A refresh that failed (vs. genuinely-absent creds) is a recoverable
            # error; don't mislabel it as "not enabled / re-login".
            if refresh_error is not None:
                raise RuntimeError(f"Failed to refresh credentials for '{self.server}': {refresh_error}") from refresh_error
        raise NotEnabled(self.server)
```
`prime-agent-runtime/src/rlm/mcp_base.py:182-188`

Результат нормализуется в обычный Python, ошибка сервера превращается в исключение, а не в
«успешный» результат:

```python
    if getattr(result, "isError", False):
        raise McpToolError("\n".join(texts) or "MCP tool returned an error")
```
`prime-agent-runtime/src/rlm/mcp_base.py:317-318`

### Что это значит для нас

- Промпт не растёт от числа MCP-тулов вообще: в системный промпт попадает только метадата скилла,
  тела `SKILL.md` модель читает по требованию (`docs/rlm.md:120`).
- Цена — латентность: TCP+OAuth+`initialize` на КАЖДЫЙ вызов тула (`mcp_base.py:278-280`), плюс
  отдельный `list_tools()` при первом обращении (`mcp_base.py:253-269`, кешируется в `self._tools`
  под `asyncio.Lock`).
- Схема тула не участвует в constrained decoding провайдера — модель пишет kwargs вручную по
  docstring'у. Дока сама предупреждает: «Discover before assuming. Tool names and argument schemas
  come from the server and can change; call `list_tools()` / `help()` rather than hardcoding»
  (`docs/mcp-integrations.md:234-236`).
- Встроенные интеграции (Linear, Notion) гейтятся кредами, пользовательские — нет: «A skill you
  drop into a skills directory is loaded like any other skill — visible to the model and imported
  into the kernel immediately, regardless of `auth.json`» (`docs/mcp-integrations.md:219-222`).

---

## Сводка: что заявкой блога не подтвердилось

| Заявка | Статус по коду |
|---|---|
| «one tool: ipython» | ✅ `allToolNames = new Set(["ipython"])`, `core/tools/index.ts:47` |
| «daemon recovers worker from session JSONL and kernel state snapshot» | ⚠️ два независимых механизма; журнал восстановления НЕ содержит состояния ядра (`worker-recovery-journal.ts:14-22`), ядро стартует заново и грузит dill-снапшот |
| «kernel state snapshot» | ⚠️ дебаунс 1.5 с, только после успешной ячейки, per-variable dill, непиклящееся молча отбрасывается (`state-snapshot.ts:5-7,91-95`) |
| «base system prompt remains immutable» | ✅ структурно (отдельный блок поверх, `system-prompt.ts:105-106`) + одна проверка id (`refinement.ts:671-673`) |
| «rollback by ID» | ⚠️ реализовано (`refinement.ts:804-822`, `/refine rollback <id>`), но ТОЛЬКО для `/refine`-правок; прямые `rlm.harness.*` из ядра затирают прошлую версию без `before` (`harness.py:366-384`) |
| «выгрузка субагента через 30 мин» | ❌ дефолт 90 минут (`settings-manager.ts:9`), 30 — лишь одно из значений в UI-селекторе (`settings-selector.ts:206`) |
| лимит на размер/число harness-записей | ❌ в коде не нашёл; ограничен только РЕНДЕР в промпт — 6 записей на вид, 180 символов (`refinement.ts:26-28`) |
| таймаут на выполнение кода | ❌ в коде не нашёл; только внешний abort + 1 с grace (`kernel/index.ts:41,905-908`) |
| песочница | ❌ отсутствует намеренно и задокументированно (`docs/rlm.md:143`) |
| GitHub issues | ⛔ проверить не смог: `gh` в окружении нет |
