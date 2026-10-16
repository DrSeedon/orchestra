cd ~/tts-bench
export HF_HOME=~/tts-bench/models/hf HF_HUB_DISABLE_XET=1
sleep 30; while pgrep -f "job_chain2.sh|job_chain1.sh" >/dev/null; do sleep 20; done
nice -n 15 /usr/bin/time -v venvs/chatter/bin/python scripts/run_chatter.py out/chatter > out/chatter.log 2>&1; echo chatter rc=$?
nice -n 15 /usr/bin/time -v venvs/oute/bin/python scripts/run_oute.py out/oute > out/oute.log 2>&1; echo oute rc=$?
# free disk: weights of models already sampled (samples and logs stay)
for d in models/coqui models/f5 models/cosy3 models/hf/hub/models--Qwen--Qwen3-TTS-12Hz-1.7B-Base; do [ -e "$d" ] && trash-put "$d"; done
trash-rm "/home/kesha/tts-bench/models/*" 2>/dev/null; echo trashed
df -h / | tail -1
avail=$(df --output=avail -BG / | tail -1 | tr -dc 0-9)
if [ "$avail" -ge 17 ]; then
  venvs/fish/bin/hf download fishaudio/s2-pro --local-dir models/s2-pro > out/fish_dl.log 2>&1 || venvs/fish/bin/huggingface-cli download fishaudio/s2-pro --local-dir models/s2-pro >> out/fish_dl.log 2>&1; echo fish dl rc=$?
  nice -n 15 /usr/bin/time -v venvs/fish/bin/python scripts/run_fish.py out/fish > out/fish.log 2>&1; echo fish rc=$?
else echo "fish skipped: only ${avail}G free"; fi
