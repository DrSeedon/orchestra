#!/bin/bash
cd /home/kesha/orchestra
D=.orchestra/tasks/luna-probe
P='Найди в этом репозитории, как Orchestra получает и нормализует лимиты Codex (5h и 7d окна), и какие тесты это покрывают. Ответь 5-8 строками с путями file:line. Ничего не меняй.'
python3 $D/rl.py > $D/limits.log
for i in 1 2; do
  codex exec -m gpt-5.6-luna -c model_reasoning_effort=high -s read-only --json "$P" > $D/run$i.jsonl 2> $D/run$i.err
  echo "run$i rc=$?" >> $D/limits.log
  python3 $D/rl.py >> $D/limits.log
done
