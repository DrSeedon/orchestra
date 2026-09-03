# research-codex-releases

- При inventory долгоживущих CLI не печатать `pgrep -af`/полный `cmdline`: argv может содержать
  credentials. Матчить аргументы внутри скрипта, наружу выводить только version/resource fields и
  boolean leak markers; перед коммитом прогонять secret-shape scan.
- После обновления CLI проверять не только новый бинарник в `PATH`, но и каждый живой процесс через
  `/proc/<pid>/exe --version`: replacement package не меняет уже запущенный executable.
