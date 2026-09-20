import sqlite3, collections, datetime as dt
db=sqlite3.connect("file:data/orchestra.db?mode=ro", uri=True)
rows=list(db.execute("select ts, session_name, tool_name, substr(replace(error_text,char(10),' '),1,70) from tool_errors order by session_name, ts"))
P=lambda s: dt.datetime.fromisoformat(s.replace("Z","+00:00")) if "T" in s else dt.datetime.fromisoformat(s)
streaks=[]; cur=None
for ts,name,tool,err in rows:
    key=(name,tool,err)
    if cur and cur["key"]==key and (P(ts)-P(cur["last"])).total_seconds()<=1800:
        cur["n"]+=1; cur["last"]=ts
    else:
        if cur and cur["n"]>=3: streaks.append(cur)
        cur={"key":key,"n":1,"first":ts,"last":ts}
if cur and cur["n"]>=3: streaks.append(cur)
streaks.sort(key=lambda s:-s["n"])
print("серий по 3+ одинаковых отказа подряд (в пределах 30 мин):", len(streaks))
print("лишних вызовов в них:", sum(s["n"]-1 for s in streaks))
by_tool=collections.Counter()
for s in streaks: by_tool[s["key"][1]]+=s["n"]-1
print("лишние вызовы по тулам:", by_tool.most_common(8))
print()
for s in streaks[:12]:
    name,tool,err=s["key"]
    mins=(P(s['last'])-P(s['first'])).total_seconds()/60
    print(f"{s['n']:3}× {mins:6.1f}мин {name[:26]:26} {tool[:28]:28} {err[:60]}")
