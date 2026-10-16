cd ~/tts-bench
export HF_HOME=~/tts-bench/models/hf HF_HUB_DISABLE_XET=1
sleep 30; while pgrep -f "job_chain1.sh" >/dev/null; do sleep 20; done
bash scripts/job_f5.sh; echo f5 done
nice -n 15 /usr/bin/time -v venvs/cosy/bin/python scripts/run_cosy.py out/cosy > out/cosy.log 2>&1; echo cosy rc=$?
