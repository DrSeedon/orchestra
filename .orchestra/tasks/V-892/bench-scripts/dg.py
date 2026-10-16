"""Deepgram nova-2 transcription: dg.py [--detect] files... → JSON lines {file, transcript, language}."""
import json, subprocess, sys, urllib.request
from pathlib import Path
key = next(l.split("=", 1)[1].strip().strip("'\"") for l in open("/home/kesha/orchestra/.env") if l.startswith("DEEPGRAM_API_KEY="))
detect = "--detect" in sys.argv
for f in [a for a in sys.argv[1:] if a != "--detect"]:
    audio = subprocess.run(["ffmpeg", "-v", "error", "-i", f, "-ac", "1", "-ar", "16000", "-f", "mp3", "-"], capture_output=True, check=True).stdout
    qs = "model=nova-2&detect_language=true&punctuate=true" if detect else "model=nova-2&language=ru&punctuate=true"
    req = urllib.request.Request(f"https://api.deepgram.com/v1/listen?{qs}", data=audio, headers={"Authorization": f"Token {key}", "Content-Type": "audio/mpeg"})
    ch = json.load(urllib.request.urlopen(req, timeout=120))["results"]["channels"][0]
    print(json.dumps({"file": f, "language": ch.get("detected_language"), "transcript": ch["alternatives"][0]["transcript"]}, ensure_ascii=False), flush=True)
