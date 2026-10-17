# item-30

Commit under review (in /home/kesha/orchestra, read-only): `ce54d49a65bce648cece8d18fc053679e41251d3`
Subject / date:
#145: #145: браузерные тесты логинятся кредами из окружения вместо скипа по auth
2026-08-07

The diff reviewed is `git -C /home/kesha/orchestra show ce54d49a65bce648cece8d18fc053679e41251d3 -- . ':(exclude).orchestra/tasks' ':(exclude).orchestra/kb'`.

## Reviewer output (verbatim)

## Summary

Проверил полный diff между указанными коммитами и связанные пути логина и списка задач. Код не менял.

## Findings

### Suggestion

- В [tests/test_frontend.py](tests/test_frontend.py:836) тест карточки просматривает только первые 25 задач. Если длинное описание есть дальше в списке, тест всё равно пропустится с сообщением, что подходящей задачи нет. Это оставляет один путь к ложному скипу; можно просматривать все страницы списка, если API поддерживает пагинацию.

### Blocking

Нет.

### Question

Нет.

## Verdict

APPROVED — изменение выполняет задачу: при наличии учётных данных браузерные тесты входят в дашборд вместо скипа из-за auth. Осталось ограничение поиска тестовой задачи первыми 25 записями.
