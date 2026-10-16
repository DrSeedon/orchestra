cd ~/tts-bench
export HF_HOME=~/tts-bench/models/hf HF_HUB_DISABLE_XET=1
nice -n 15 /usr/bin/time -v venvs/oute/bin/python scripts/run_oute.py out/oute > out/oute.log 2>&1; echo oute rc=$?
