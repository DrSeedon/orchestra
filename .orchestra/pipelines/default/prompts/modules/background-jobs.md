<background-jobs>
## Background jobs — the two things the tool description does not tell you

Types, parameters and examples live in the `bg_create` tool description; it is the owner, and
`base.md` already carries the "never sleep or poll" rule. Only these are yours:

- **`message` must explain WHY, not WHAT to check.** It is read by a future agent with none of
  today's context: "НАПОМИНАНИЕ: начислить надбавку 10% к окладу с декабря 2026", not "check X".
- **A job you created is yours to cancel.** A recurring job outlives the reason it was created;
  when that reason is gone, `bg_cancel` it instead of letting it wake agents forever.
- **Для проверки после окончания работы используй переиспользуемый idle-сторож на себе:**
  `bg_create(type="idle", timeout_seconds=0, message="Проверь результат задачи: собери доклады,
  проверь ошибки доставки; если работа завершена — дай итог и отмени этот сторож.")`.
  Он срабатывает, когда ты idle, никто из твоих потомков не выполняет ход и нет других
  активных фоновых заданий в этом дереве. Сам сторож не удерживает статус waiting.
  Повторный bg_create(type="idle") заменяет твой прежний сторож. Новая активность вновь
  вооружает его; собственное пробуждение и ответ не создают бесконечный цикл.
  Это сигнал проверить результат, а не доказательство, что работа успешна или стояла:
  доклады могут не дойти из-за отказа доставки. Проверяй ошибки и фактические результаты.
  Зависший running-воркер не считается idle; этот тип не заменяет диагностику зависаний.
  Будить по таймеру каждые 30 минут по умолчанию больше не требуется.
</background-jobs>
