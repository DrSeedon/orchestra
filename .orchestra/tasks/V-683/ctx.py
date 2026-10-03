import sqlite3, sys
db = sqlite3.connect("file:/home/kesha/orchestra/data/orchestra.db?mode=ro", uri=True)
S = "85f0ba7a-0d8a-401e-a909-eb57c40fb02f"
a, b = int(sys.argv[1]), int(sys.argv[2]); n = int(sys.argv[3]) if len(sys.argv)>3 else 350
for i, ts, t, o, c, tn in db.execute("select id, ts, type, origin, content, tool_name from logs where session_id=? and id between ? and ? and type in ('user_message','text','tool','compact_event','thinking') order by id", (S,a,b)):
    if t=='tool':
        if tn and ('send_message' in tn or 'spawn' in tn or 'reply' in tn.lower() or 'telegram' in tn.lower() or tn in('Write','Edit','Bash')):
            print(f"#{i} {ts[5:16]} TOOL {tn}: {c[:n//2]!r}")
        continue
    print(f"#{i} {ts[5:16]} {t}/{o}: {c[:n].replace(chr(10),' ')}")
