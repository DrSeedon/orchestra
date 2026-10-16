cd ~/tts-bench
export HF_HOME=~/tts-bench/models/hf HF_HUB_DISABLE_XET=1
[ -e models/s2-pro ] && trash-put models/s2-pro && trash-rm "/home/kesha/tts-bench/models/s2-pro" 2>/dev/null; df -h / | tail -1
nice -n 15 /usr/bin/time -v venvs/chatter/bin/python scripts/run_chatter.py out/chatter > out/chatter.log 2>&1; echo chatter rc=$?
nice -n 15 /usr/bin/time -v venvs/oute/bin/python scripts/run_oute.py out/oute > out/oute.log 2>&1; echo oute rc=$?
df -h / | tail -1
