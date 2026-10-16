cd ~/tts-bench
export HF_HOME=~/tts-bench/models/hf HF_HUB_DISABLE_XET=1
sleep 60; while pgrep -f "job_f5.sh|run_f5.py" >/dev/null; do sleep 20; done
nice -n 15 /usr/bin/time -v venvs/chatter/bin/python scripts/run_chatter.py out/chatter > out/chatter.log 2>&1; echo chatter rc=$?
nice -n 15 /usr/bin/time -v venvs/qwen/bin/python scripts/run_qwen.py out/qwen > out/qwen.log 2>&1; echo qwen rc=$?
