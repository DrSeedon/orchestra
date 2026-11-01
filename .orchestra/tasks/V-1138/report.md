# V-1138 — regenerate tailwind.css after V-1137

- Ran `bash scripts/build-tailwind.sh` (pinned npx tailwindcss@3.4.17). No manual CSS edits, no dependency/JS/HTML changes.
- `app/static/css/vendor/tailwind.css`: 21170 -> 20940 bytes. Rule-level diff removes exactly three rules, all used only by the deleted queue panel:
  `.bg-slate-800\/70`, `.text-red-300`, `.hover\:text-red-200:hover`. Nothing added.
  (`hover:text-red-300` in dashboard.html line 264 is a different class and remains.)
- Check: `uv run --frozen python -m pytest tests/test_tailwind_css.py -q` -> 3 passed (with conftest, no --noconftest needed).
- Not run: full suite / browser shards (parent CI covers).

Parent host acceptance: normal-fixture test_tailwind_css.py passed 3 tests in 5.74s. Imported app: `/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-queue-css-build/app/__init__.py`. Independent rule comparison confirmed exactly the listed three selectors removed and no additions; restoring old CSS through the committed test module CSS-path override made its exact-build check fail. All three changed files passed secret shape, known-value and forbidden-string checks; diff clean. After merge, live static CSS returned HTTP200 and byte-matched main. No restart. Full verification proceeds through actual push CI; raw failed prior-run evidence is private under V-1137.
