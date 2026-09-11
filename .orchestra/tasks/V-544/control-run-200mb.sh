#!/bin/bash
set -u
DIR=/home/kesha/orchestra/data/v544-probe
OUT=$DIR/result.txt
F=$DIR/v544-probe-200mb.bin
TOKEN=<из окружения сервиса: TG_BRIDGE_TOKEN>
CHAT=-1003760207564
THREAD=82134
: > "$OUT"
if [ ! -f "$F" ]; then
  head -c 209715200 /dev/urandom > "$F"
fi
echo "file_bytes=$(stat -c %s "$F")" >> "$OUT"
START=$(date +%s.%N)
HTTP=$(curl -s -o "$DIR/response.json" -w '%{http_code}' --max-time 1800 \
  -F "chat_id=$CHAT" -F "message_thread_id=$THREAD" \
  -F "caption=тест #V-544: контрольный замер потолка документа через локальный Bot API (200 МБ, случайные байты). Удалять не нужно, файл технический." \
  -F "document=@$F;filename=v544-probe-200mb.bin" \
  "http://localhost:8081/bot$TOKEN/sendDocument")
END=$(date +%s.%N)
echo "http_code=$HTTP" >> "$OUT"
echo "seconds=$(echo "$END - $START" | bc)" >> "$OUT"
echo "response=$(head -c 1200 "$DIR/response.json")" >> "$OUT"
cat "$OUT"
