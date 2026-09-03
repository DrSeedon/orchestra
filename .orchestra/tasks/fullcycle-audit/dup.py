import json,re
ev=json.load(open("/tmp/fcaudit/events.json"))
for ts,ag,tool,args in ev:
    if "send_message" not in tool: continue
    try:m=json.loads(args).get("message","")
    except Exception:continue
    if ag=="feat-usage-analytics" and m.strip().startswith("DONE"):
        print("=== DONE-сообщение feat-usage-analytics ===");print(m[:1800]);break
