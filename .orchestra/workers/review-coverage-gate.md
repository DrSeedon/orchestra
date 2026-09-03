# review-coverage-gate

- Историческая квитанция считается существовавшей к границе события только если и `requested_at`, и non-null `completed_at` не позже этой границы; фильтр только по старту завышает покрытие.
- Если policy activation может появиться после admission, любой сохранённый `not_active` надо перепроверять непосредственно перед необратимым executor/commit; иначе очередь, принятая до активации, обходит новый гейт.
- `.codex/skills/codex-debate/SKILL.md` — reconnect-time untracked projection: коммитить только canonical `.orchestra/pipelines/default/prompts/skills/codex-debate.md`, projection проверять через `cmp`, не force-add.
- Тесты review-policy требуют единственного вхождения route anchors; новый operational-блок ссылается на номер существующего gate, а не повторяет его точный label.
