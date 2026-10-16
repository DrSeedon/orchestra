set -e
cd ~/tts-bench; mkdir -p models/f5/misha models/f5/espeech
export HF_HOME=~/tts-bench/models/hf HF_HUB_DISABLE_XET=1
B=https://huggingface.co
dl(){ [ -s "$2" ] || { mkdir -p "$(dirname "$2")"; curl -sSfL --http1.1 --retry 8 --retry-all-errors -C - -o "$2.part" "$1" && mv "$2.part" "$2"; }; }
dl $B/Misha24-10/F5-TTS_RUSSIAN/resolve/main/F5TTS_v1_Base_v4_winter/model_212000.safetensors models/f5/misha/F5TTS_v1_Base_v4_winter/model_212000.safetensors
dl $B/Misha24-10/F5-TTS_RUSSIAN/resolve/main/F5TTS_v1_Base/vocab.txt models/f5/misha/F5TTS_v1_Base/vocab.txt
dl $B/ESpeech/ESpeech-TTS-1_RL-V2/resolve/main/espeech_tts_rlv2.pt models/f5/espeech/espeech_tts_rlv2.pt
dl $B/ESpeech/ESpeech-TTS-1_RL-V2/resolve/main/vocab.txt models/f5/espeech/vocab.txt
df -h / | tail -1
nice -n 15 /usr/bin/time -v venvs/f5/bin/python scripts/run_f5.py out/f5 > out/f5.log 2>&1
echo rc=$?
