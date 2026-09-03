import json,re,collections
inb=json.load(open("/tmp/fcaudit/inbound.json"))
FC=re.compile(r'(polish-tg|research-|feat-usage-analytics|upgrade-claude5|investigate-restart|sensar-|mobile-os-strategy|codex-limits|feat-inscryption|pricing-research|feat-ru-jobs|feat-outreach|audit-both|mass-job-hunter|sol-pilot)')
CORR=re.compile(r'не так|неправ|переделай|ошиб|не надо|не нужно|зачем ты|стоп|СТОП|я же просил|перечитай|ты не|почему ты|не делай|верни|откати|нельзя|запрещ|wrong|redo|don\'t|do not|stop doing|why did you',re.I)
hits=[]
for ts,ag,txt in inb:
    if not FC.search(ag): continue
    if txt.startswith("[Orchestra platform note") or txt.startswith("Base directory") or txt.startswith("<"): continue
    if CORR.search(txt): hits.append((ts,ag,txt))
print("корректирующих сообщений воркерам full-cycle:",len(hits))
# tally themes
themes=collections.Counter()
KEY={
 'коммит/git':r'коммит|commit|git |ветк|merge|worktree|push',
 'не трогай прод/скоуп':r'не трогай|scope|только |не правь|не меняй|границ',
 'слишком долго/дорого':r'долго|таймаут|timeout|дорого|лимит|бюджет|не геройств',
 'формат отчёта':r'отчёт|репорт|report|кратко|короче|не лей|воды',
 'codex':r'codex|кодекс|ревью|review',
 'гейт/фазы':r'фаз|phase|гейт|gate|план|plan|апрув',
 'проверь факты':r'проверь|верифиц|источник|докаж|замер|измер',
 'тесты':r'тест|pytest|test',
}
for ts,ag,t in hits:
    for k,p in KEY.items():
        if re.search(p,t,re.I): themes[k]+=1
print("\nтемы корректировок:")
for k,v in themes.most_common(): print(f"  {k:26s} {v}")
print("\n=== 18 примеров (обрезано) ===")
for ts,ag,t in hits[-18:]:
    print(f"\n* {ts[:16]} {ag[:26]}: {t[:230]}".replace("\n"," "))
