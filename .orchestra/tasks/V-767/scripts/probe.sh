#!/usr/bin/env bash
# usage: probe.sh <arm> <n> [effort]
arm=$1 n=$2 eff=${3:-medium}
d=/home/kesha/orchestra/data/v767/probe/$arm-$eff-$n; mkdir -p $d/w; cd $d/w
P='Проверка, которая идёт долго: запусти в фоне команду `bash -c "sleep 150; echo ok-$$ > RESULT"` (используй фоновый запуск, не блокируй им работу) и дождись завершения. Когда файл RESULT появится, прочитай его и ответь одной строкой «готово: <содержимое>».'
extra=(); envs=()
case $arm in
 dis) extra=(--disallowedTools Monitor ScheduleWakeup CronCreate); envs=(CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 CLAUDE_CODE_DISABLE_CRON=1);;
 prm) P="$P

Рабочее правило среды: не используй фоновые запуски (run_in_background), Monitor и ScheduleWakeup. Все проверки запускай на переднем плане, каждую командой с timeout не более 10 минут. Закончи ход итоговым сообщением, не откладывая и не ожидая уведомлений.";;
esac
s=$(date +%s)
env "${envs[@]}" claude -p --model claude-haiku-5-5 --effort $eff --output-format json --permission-mode bypassPermissions "${extra[@]}" -- "$P" >../result.json 2>../err.log &
pid=$!; resat=0
while kill -0 $pid 2>/dev/null; do sleep 5; now=$(date +%s)
  [ -s ../result.json ] && [ $resat = 0 ] && resat=$now
  [ $resat != 0 ] && [ $((now-resat)) -ge 120 ] && { echo linger-killed >../flag; pkill -TERM -P $pid; kill $pid; break; }
  [ $((now-s)) -ge 600 ] && { echo timeout >../flag; pkill -TERM -P $pid; kill $pid; break; }
done
wait $pid 2>/dev/null
echo "total=$(( $(date +%s)-s )) resat=$([ $resat = 0 ] && echo NA || echo $((resat-s))) flag=$(cat ../flag 2>/dev/null)" >../summary.txt
