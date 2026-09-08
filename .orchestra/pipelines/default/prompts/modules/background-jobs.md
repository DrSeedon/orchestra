<background-jobs>
## Background jobs — the two things the tool description does not tell you

Types, parameters and examples live in the `bg_create` tool description; it is the owner, and
`base.md` already carries the "never sleep or poll" rule. Only these are yours:

- **`message` must explain WHY, not WHAT to check.** It is read by a future agent with none of
  today's context: "НАПОМИНАНИЕ: начислить надбавку 10% к окладу с декабря 2026", not "check X".
- **A job you created is yours to cancel.** A recurring job outlives the reason it was created;
  when that reason is gone, `bg_cancel` it instead of letting it wake agents forever.
- **Оставляешь воркеров работать без себя (ночь, долгая отлучка) — в ТОМ ЖЕ ходе поставь
  сторожа, который будит ТЕБЯ не реже чем раз в 30 минут.** Решение владельца 08.09.2026,
  дословно: «ночная работа это поставить сторожа который бы будил каждые пол часа на проверку
  всего актуализации а то зависнет так и все». Проверка «глазами в конце хода» ночью не
  работает по устройству: ходов нет, и молчание неотличимо от работы. Замер 07→08.09 в соседнем
  портфеле: четыре воркера залипли через минуту после раздачи ночных заданий и простояли
  **9 часов с нулём коммитов**, а оркестратор всё это время считал смену идущей и доложил
  «все четверо работают».
  Сторож проверяет ДВИЖЕНИЕ, а не статус: `idle` у сессии и `QUEUED` у доставки показывались
  все девять часов простоя. Считай файлы, изменённые в worktree воркеров за последний интервал,
  и коммиты за него же; ноль по всем — повод разбудить. Рабочая форма —
  `bg_create(type="cron_command", ...)` с `pattern`, ловящим этот ноль: тогда ход тратится
  только когда всё встало. Смена кончилась — `bg_cancel`.
</background-jobs>
