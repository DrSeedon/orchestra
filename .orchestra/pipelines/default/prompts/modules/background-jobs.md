## Background jobs — what the tool description does not tell you

Types, parameters and examples live in the `bg_create` tool description; it is the owner, and
`base.md` already carries the "never sleep or poll" rule. Only these are yours:

- **`message` must explain WHY, not WHAT to check.** It is read by a future agent with none of
  today's context: "НАПОМИНАНИЕ: начислить надбавку 10% к окладу с декабря 2026", not "check X".
- **Never create a timer to retry a delivery.** A message or first task that the quota gate
  holds back is accepted into a durable queue (`WAITING_QUOTA`) and goes out by itself, in
  order, when the gate opens — also after a restart. The receipt gives an estimate; do not
  resend and do not wake yourself to "retry in N hours": each such wake is a paid turn.
  To withdraw a queued message use `cancel_message_delivery`; read its state with
  `message_delivery_status`.
- **A job you created is yours to cancel.** A recurring job outlives the reason it was created;
  when that reason is gone, `bg_cancel` it instead of letting it wake agents forever.
- **Отчёт воркера не нужно страховать сторожем.** Если ход воркера кончился, а он тебе
  ничего не написал (ошибка, обрыв, смерть процесса, рестарт Orchestra), платформа сама,
  durable и ровно один раз, присылает тебе сообщение `[auto-report]`: кто, чем кончился ход,
  последний вывод. Нормальный DONE от воркера дубля не даёт. Не ставь для этого `bg_create`
  и не жди по таймеру. Получив `[auto-report]`, проверь фактический результат, а не только
  текст: он говорит о конце хода, а не об успехе работы.
