# commerce-agents-study

- При аудите vendor blueprint сначала найди его собственный inventory/checklist (`docs/safety.md`, review command, skill index), затем сверяй каждую статью с вызывающим кодом: в #507 это быстро вскрыло `20/20` guardrails и четыре article↔code расхождения, которые README-пересказ скрыл бы.
- Reviewer-цитату проверяй exact-match до слова «approved»: в #507 Luna заменила `;` на `.`, поэтому содержательный `APPROVED` по canonical evidence contract остался «вердикта нет» и третий prose-round был запрещён потолком.
