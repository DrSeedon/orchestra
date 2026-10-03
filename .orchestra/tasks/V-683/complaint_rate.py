import sqlite3, re, collections
db = sqlite3.connect("file:/home/kesha/orchestra/data/orchestra.db?mode=ro", uri=True)
S = "85f0ba7a-0d8a-401e-a909-eb57c40fb02f"
rows = db.execute("select ts, content from logs where session_id=? and type='user_message' and origin='user' order by id", (S,)).fetchall()
# маркеры недовольства/исправления: определены ДО подсчёта
pat = re.compile(r"не то\b|не так\b|опять|снова|я же (говорил|сказал|просил)|100 раз|сто раз|забыл|забываешь|сломал|сломано|слетел|полетел|хуйн|жесть|капец|почему|зачем|не понял|ты не понимаешь|где (сам|переделан|ссылк|презентац|описани|рилс|повтор)|перепроверь|ошиб|неверно|наезжают|за рамки|все смешалось|делаешь что-то сво|не подходят", re.I)
def period(ts):
    d = ts[:10]
    if d < "2026-09-05": return "0_<05.09"
    if d < "2026-09-23": return "1_05.09-22.09 (Opus5 high)"
    return "2_23.09-03.10 (Opus5.5 medium)"
c = collections.Counter(); h = collections.Counter(); katya = collections.Counter(); kh = collections.Counter()
for ts, txt in rows:
    p = period(ts); c[p]+=1
    hit = bool(pat.search(txt)); h[p]+=hit
    if "Екатерина" in txt:
        katya[p]+=1; kh[p]+=hit
for p in sorted(c):
    print(f"{p}: all {h[p]}/{c[p]} = {h[p]/c[p]:.1%}; from Katya {kh[p]}/{katya[p]} = {(kh[p]/katya[p] if katya[p] else 0):.1%}")
