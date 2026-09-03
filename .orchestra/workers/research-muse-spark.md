# research-muse-spark

- В zsh не использовать `path` как loop/local variable: это special array `$path`, его перезапись делает `curl`, `sed` и другие команды недоступными в текущем shell. Использовать `endpoint_path` или другой task-specific name.
