# Личная память оркестратора

Порядок работы с памятью: `.orchestra/pipelines/default/prompts/modules/knowledge.md`.
Прежние личные наблюдения доступны через `.orchestra/kb/history.md`.

- **Боевая БД задана `ORCHESTRA_DB_PATH`, а не `data/orchestra.db`.** 09.09 объявил владельцу «при следующем рестарте платформа не поднимется», померив старую базу (`user_version=0`, 48 таблиц); живой процесс с 08.09 работает на `data/storage-final-vps-20260908/orchestra.db` (`user_version=1`), старый файл не пишется с 08.09 15:15 UTC. Различитель: `ls -l /proc/$(systemctl show orchestra --property=MainPID --value)/fd | grep '\.db'` плюс `ORCHESTRA_DB_PATH` из `/proc/<pid>/environ`. Любой замер по `turn_usage`/`logs` из старого файла молча обрывается на дате переезда.
- **Перед `trash <каталог>` проверяй `git ls-files <каталог>`, а не вывод `git status`.** 08.09 снёс каталог целиком из-за одного `??`-файла и удалил 7 отслеживаемых артефактов; спасло `git checkout -- <каталог>`. Удалять надо ровно тот путь, который показал `git status`, а не его родителя.
