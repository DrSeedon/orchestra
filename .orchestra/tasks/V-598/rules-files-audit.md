# V-598 — аудит файлов правил

Файлов найдено: 156.
Групп дублей по sha256: 25.
Групп по каталогу (каталог содержит минимум два файла правил): 39.
Каталогов с перекосом: 76.

## Область и наблюдаемый доступ

Имена и каталоги поиска заданы поручением V-598; исключены каталоги .git, node_modules, .venv, worktrees, data/, archive/.

Проверка listener:
```text
LISTEN 0      128    127.0.0.1:2222 0.0.0.0:*
```

Проверка SSH (hostname; pwd):
```text
maxim-911aird
/home/maxim
```

## Таблица файлов

| машина | абсолютный путь | тип (обычный файл / симлинк → цель / битый симлинк) | размер в байтах | sha256 содержимого (для симлинка — sha256 цели) | mtime | git: отслеживается / не отслеживается / вне репозитория |
|---|---|---|---:|---|---|---|
| VPS | /home/kesha/.claude/CLAUDE.md | обычный файл | 4495 | 14625f965a41fe649b031a7349fe07598a3bdadaf146a53f75857e085bdbe5ad | 2026-09-20T05:49:22.017788+00:00 | вне репозитория |
| VPS | /home/kesha/.codex/AGENTS.md | симлинк → /home/kesha/.claude/CLAUDE.md | 4495 | 14625f965a41fe649b031a7349fe07598a3bdadaf146a53f75857e085bdbe5ad | 2026-09-13T13:51:22.177173+00:00 | вне репозитория |
| VPS | /home/kesha/ai-table-i1-deploy/app.new/CLAUDE.md | обычный файл | 9061 | 22885957ac76bb03e923e18d0ee23ccd7cd005124d927cb3b8c483295f7f33ed | 2026-08-19T10:45:00+00:00 | вне репозитория |
| VPS | /home/kesha/bench219/p2-1/CLAUDE.md | обычный файл | 62362 | fd60465ffdbaec86bad04fa1f302e15a8dfb2a199512c0f3bc17c114f853a46e | 2026-08-12T08:57:38.430135+00:00 | отслеживается |
| VPS | /home/kesha/bench219/p2-2/CLAUDE.md | обычный файл | 62362 | fd60465ffdbaec86bad04fa1f302e15a8dfb2a199512c0f3bc17c114f853a46e | 2026-08-12T08:57:41.443122+00:00 | отслеживается |
| VPS | /home/kesha/bench219/p2-3/CLAUDE.md | обычный файл | 62362 | fd60465ffdbaec86bad04fa1f302e15a8dfb2a199512c0f3bc17c114f853a46e | 2026-08-12T08:57:44.816107+00:00 | отслеживается |
| VPS | /home/kesha/bench219/p2-4/CLAUDE.md | обычный файл | 62362 | fd60465ffdbaec86bad04fa1f302e15a8dfb2a199512c0f3bc17c114f853a46e | 2026-08-12T09:12:45.036902+00:00 | отслеживается |
| VPS | /home/kesha/bench219/p2-5/CLAUDE.md | обычный файл | 62362 | fd60465ffdbaec86bad04fa1f302e15a8dfb2a199512c0f3bc17c114f853a46e | 2026-08-12T09:12:47.515903+00:00 | отслеживается |
| VPS | /home/kesha/bench219/p2-6/CLAUDE.md | обычный файл | 62362 | fd60465ffdbaec86bad04fa1f302e15a8dfb2a199512c0f3bc17c114f853a46e | 2026-08-12T09:33:45.816977+00:00 | отслеживается |
| VPS | /home/kesha/bench219/p2-7/CLAUDE.md | обычный файл | 62362 | fd60465ffdbaec86bad04fa1f302e15a8dfb2a199512c0f3bc17c114f853a46e | 2026-08-12T09:33:49.153966+00:00 | отслеживается |
| VPS | /home/kesha/bench219/p2-8/CLAUDE.md | обычный файл | 62362 | fd60465ffdbaec86bad04fa1f302e15a8dfb2a199512c0f3bc17c114f853a46e | 2026-08-12T09:41:08.600430+00:00 | отслеживается |
| VPS | /home/kesha/bench219/repo-a/CLAUDE.md | обычный файл | 62362 | fd60465ffdbaec86bad04fa1f302e15a8dfb2a199512c0f3bc17c114f853a46e | 2026-08-12T08:20:43.040583+00:00 | отслеживается |
| VPS | /home/kesha/bench219/repo-b/CLAUDE.md | обычный файл | 62362 | fd60465ffdbaec86bad04fa1f302e15a8dfb2a199512c0f3bc17c114f853a46e | 2026-08-12T08:20:45.813570+00:00 | отслеживается |
| VPS | /home/kesha/katya-work/AGENTS.md | обычный файл | 20891 | fe863181ab576423ed523559bef00506b33485036d73cb5e36b03b9a89538ae1 | 2026-09-18T09:40:22.048170+00:00 | отслеживается |
| VPS | /home/kesha/katya-work/CLAUDE.md | симлинк → /home/kesha/katya-work/AGENTS.md | 20891 | fe863181ab576423ed523559bef00506b33485036d73cb5e36b03b9a89538ae1 | 2026-09-20T05:55:37.473514+00:00 | отслеживается |
| VPS | /home/kesha/orchestra-scratch/237/mini-orchestra/CLAUDE.md | обычный файл | 157351 | 74afd0d1a650a28e325b7355908b016ef9f9f118b0d0deb57931b3d9c69d243f | 2026-08-13T15:49:18.343523+00:00 | отслеживается |
| VPS | /home/kesha/orchestra-storage-deploy/AGENTS.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-08T11:38:42.483256+00:00 | отслеживается |
| VPS | /home/kesha/orchestra-storage-deploy/CLAUDE.md | симлинк → /home/kesha/orchestra-storage-deploy/AGENTS.md | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-20T05:55:37.498514+00:00 | отслеживается |
| VPS | /home/kesha/orchestra/AGENTS.md | обычный файл | 12542 | e7a39696914fd8f68a2efd7a79b99edbd728bbd68734a89a6395669cb70fd9e3 | 2026-09-20T05:55:16.845639+00:00 | отслеживается |
| VPS | /home/kesha/orchestra/CLAUDE.md | симлинк → /home/kesha/orchestra/AGENTS.md | 12542 | e7a39696914fd8f68a2efd7a79b99edbd728bbd68734a89a6395669cb70fd9e3 | 2026-09-20T05:54:43.836839+00:00 | отслеживается |
| VPS | /home/kesha/projects/University/CLAUDE.md | обычный файл | 20457 | 68d9b2255c79037b0bd43a96fcce94a581c010652d76770adc0bfcdebf3822e6 | 2026-09-20T05:57:21.494974+00:00 | отслеживается |
| VPS | /home/kesha/projects/VPN-Service/AGENTS.md | обычный файл | 35308 | af7272c09fe061e10b215a9a5d1045ce8eb4705435794c5652ddab0ec9a91609 | 2026-09-10T07:55:50.685647+00:00 | не отслеживается |
| VPS | /home/kesha/projects/VPN-Service/CLAUDE.md | обычный файл | 35308 | af7272c09fe061e10b215a9a5d1045ce8eb4705435794c5652ddab0ec9a91609 | 2026-09-10T07:55:50.685647+00:00 | отслеживается |
| VPS | /home/kesha/projects/ai-table-mvp/CLAUDE.md | обычный файл | 9061 | 22885957ac76bb03e923e18d0ee23ccd7cd005124d927cb3b8c483295f7f33ed | 2026-08-19T06:51:42.464452+00:00 | отслеживается |
| VPS | /home/kesha/projects/comfy-image-pipeline/AGENTS.md | обычный файл | 99053 | bb9556429c43f8d91c8c83f3b1f36d88e94de7492b94fc84f2e446c1aa78c40f | 2026-09-19T04:44:34.510921+00:00 | отслеживается |
| VPS | /home/kesha/projects/comfy-image-pipeline/CLAUDE.md | обычный файл | 99053 | bb9556429c43f8d91c8c83f3b1f36d88e94de7492b94fc84f2e446c1aa78c40f | 2026-09-19T04:44:34.510921+00:00 | отслеживается |
| VPS | /home/kesha/projects/dnd-game-master.rsync-old/AGENTS.md | обычный файл | 11891 | 2e78ab1faed823f5ebcfd08de80478fc5efb27c4ed589ad4e4cf6716d5b2c83f | 2026-07-26T06:33:01.128876+00:00 | не отслеживается |
| VPS | /home/kesha/projects/dnd-game-master.rsync-old/CLAUDE.md | обычный файл | 11891 | 2e78ab1faed823f5ebcfd08de80478fc5efb27c4ed589ad4e4cf6716d5b2c83f | 2026-07-26T06:33:01.128876+00:00 | не отслеживается |
| VPS | /home/kesha/projects/dnd-game-master/AGENTS.md | обычный файл | 9241 | ca5b50cb54635b112dd94a49ee68221c2a565fb9b0f35146bf4749bbee84e990 | 2026-09-19T07:49:09.217372+00:00 | отслеживается |
| VPS | /home/kesha/projects/dnd-game-master/CLAUDE.md | обычный файл | 26998 | 5c02c8f4ce2c1f5be2bb916ab7f3e97fba7d9990992af92c499c4c8052c676cc | 2026-09-19T07:49:26.096260+00:00 | отслеживается |
| VPS | /home/kesha/projects/kesha-tg-bot/AGENTS.md | обычный файл | 50626 | f2b46dc955f82b47d5f65937229ee6852be2e865b47dfa9958d167af2c507a99 | 2026-09-18T09:30:23.587176+00:00 | не отслеживается |
| VPS | /home/kesha/projects/kesha-tg-bot/CLAUDE.md | обычный файл | 50698 | aa986e14a4b6181aba611c2888ea4be9761949f562fb22944944cdca95cff980 | 2026-09-20T04:09:59.272722+00:00 | отслеживается |
| VPS | /home/kesha/projects/mfm-2026-infra/CLAUDE.md | обычный файл | 99053 | bb9556429c43f8d91c8c83f3b1f36d88e94de7492b94fc84f2e446c1aa78c40f | 2026-09-19T08:54:42.766702+00:00 | вне репозитория |
| VPS | /home/kesha/projects/seedon/AGENTS.md | обычный файл | 82642 | d44b08facf18e6ae3f328809d972f248b332397b6f0423fd787136b40264392f | 2026-09-19T10:22:11.314686+00:00 | не отслеживается |
| VPS | /home/kesha/projects/seedon/CLAUDE.md | обычный файл | 82642 | d44b08facf18e6ae3f328809d972f248b332397b6f0423fd787136b40264392f | 2026-09-19T10:22:11.306686+00:00 | отслеживается |
| VPS | /home/kesha/projects/seedon/infra/CLAUDE.md | обычный файл | 2538 | 253b07a96cf0706f35b5a7393e179073c54be627a112ec6d1f5bb2dbfcceeece | 2026-08-03T07:14:24.688205+00:00 | отслеживается |
| VPS | /home/kesha/split/mfm-2026-globe/CLAUDE.md | обычный файл | 99053 | bb9556429c43f8d91c8c83f3b1f36d88e94de7492b94fc84f2e446c1aa78c40f | 2026-09-19T08:13:49.991490+00:00 | отслеживается |
| VPS | /home/kesha/split/mfm-2026-oil-paint/CLAUDE.md | обычный файл | 99053 | bb9556429c43f8d91c8c83f3b1f36d88e94de7492b94fc84f2e446c1aa78c40f | 2026-09-19T08:12:20.211091+00:00 | отслеживается |
| VPS | /home/kesha/split/mfm-2026-photobooth/CLAUDE.md | обычный файл | 99053 | bb9556429c43f8d91c8c83f3b1f36d88e94de7492b94fc84f2e446c1aa78c40f | 2026-09-19T08:16:54.793251+00:00 | отслеживается |
| VPS | /home/kesha/split/mfm-2026-voice/CLAUDE.md | обычный файл | 99053 | bb9556429c43f8d91c8c83f3b1f36d88e94de7492b94fc84f2e446c1aa78c40f | 2026-09-19T08:15:18.927894+00:00 | отслеживается |
| VPS | /home/kesha/workspace/project/CLAUDE.md | обычный файл | 30704 | 818a47747ba95b3645c812f150d7885bdd170c35d895eddfad135b4b9c228c52 | 2026-07-06T14:37:28.836612+00:00 | не отслеживается |
| VPS | /opt/ai-table-i1/app.previous-20260819T034912Z/CLAUDE.md | обычный файл | 3328 | 89268bc344d265c691c6d6970ffe60bfc3473c73dcb48513caed43d20259f32a | 2026-08-19T03:40:32+00:00 | вне репозитория |
| VPS | /opt/ai-table-i1/app.previous-20260819T040607Z/CLAUDE.md | обычный файл | 3328 | 89268bc344d265c691c6d6970ffe60bfc3473c73dcb48513caed43d20259f32a | 2026-08-19T03:48:58+00:00 | вне репозитория |
| VPS | /opt/ai-table-i1/app.previous-20260819T041229Z/CLAUDE.md | обычный файл | 3328 | 89268bc344d265c691c6d6970ffe60bfc3473c73dcb48513caed43d20259f32a | 2026-08-19T04:05:51+00:00 | вне репозитория |
| VPS | /opt/ai-table-i1/app.previous-20260819T044156Z/CLAUDE.md | обычный файл | 3328 | 89268bc344d265c691c6d6970ffe60bfc3473c73dcb48513caed43d20259f32a | 2026-08-19T04:12:14+00:00 | вне репозитория |
| VPS | /opt/ai-table-i1/app.previous-20260819T044347Z/CLAUDE.md | обычный файл | 5868 | dc520fad8de8a747c0c05e57578cdf247398920899a754dca73bc3b01878f82b | 2026-08-19T04:39:35+00:00 | вне репозитория |
| VPS | /opt/ai-table-i1/app.previous-20260819T053335Z/CLAUDE.md | обычный файл | 5868 | dc520fad8de8a747c0c05e57578cdf247398920899a754dca73bc3b01878f82b | 2026-08-19T04:43:29+00:00 | вне репозитория |
| VPS | /opt/ai-table-i1/app.previous-20260819T065231Z/CLAUDE.md | обычный файл | 8215 | 59574a6fb60360d4564a582dbf8c54c25e49bafbc8e8a265a58bb51daef0115e | 2026-08-19T05:30:06+00:00 | вне репозитория |
| VPS | /opt/ai-table-i1/app.previous-20260819T070110Z/CLAUDE.md | обычный файл | 9061 | 22885957ac76bb03e923e18d0ee23ccd7cd005124d927cb3b8c483295f7f33ed | 2026-08-19T06:51:42+00:00 | вне репозитория |
| VPS | /opt/ai-table-i1/app.previous-20260819T102713Z/CLAUDE.md | обычный файл | 9061 | 22885957ac76bb03e923e18d0ee23ccd7cd005124d927cb3b8c483295f7f33ed | 2026-08-19T07:00:51+00:00 | вне репозитория |
| VPS | /opt/ai-table-i1/app.previous-20260819T102841Z/CLAUDE.md | обычный файл | 9061 | 22885957ac76bb03e923e18d0ee23ccd7cd005124d927cb3b8c483295f7f33ed | 2026-08-19T10:23:23+00:00 | вне репозитория |
| VPS | /opt/ai-table-i1/app.previous-20260819T104121Z/CLAUDE.md | обычный файл | 9061 | 22885957ac76bb03e923e18d0ee23ccd7cd005124d927cb3b8c483295f7f33ed | 2026-08-19T10:28:39+00:00 | вне репозитория |
| VPS | /opt/ai-table-i1/app.previous-20260819T104518Z/CLAUDE.md | обычный файл | 9061 | 22885957ac76bb03e923e18d0ee23ccd7cd005124d927cb3b8c483295f7f33ed | 2026-08-19T10:37:23+00:00 | вне репозитория |
| VPS | /opt/ai-table-i1/app/CLAUDE.md | обычный файл | 9061 | 22885957ac76bb03e923e18d0ee23ccd7cd005124d927cb3b8c483295f7f33ed | 2026-08-19T10:45:00+00:00 | вне репозитория |
| VPS | /opt/cog-second-brain/AGENTS.md | обычный файл | 101448 | 278ae296b7d3dfaf53e2b0d7d859f1211c76346d0103839ce90fb12e683b7d37 | 2026-09-18T08:34:48.264539+00:00 | отслеживается |
| VPS | /opt/cog-second-brain/CLAUDE.md | симлинк → /opt/cog-second-brain/AGENTS.md | 101448 | 278ae296b7d3dfaf53e2b0d7d859f1211c76346d0103839ce90fb12e683b7d37 | 2026-09-20T05:53:31.836274+00:00 | отслеживается |
| VPS | /opt/cog-second-brain/GEMINI.md | обычный файл | 1996 | d9293f92cc11d8c5df9d0c672227f7ec8df9ff13f5cf98d6e6dd34a274840e7f | 2026-05-05T16:13:49+00:00 | отслеживается |
| VPS | /opt/kesha-bot/AGENTS.md | обычный файл | 50698 | aa986e14a4b6181aba611c2888ea4be9761949f562fb22944944cdca95cff980 | 2026-09-20T04:20:08.781998+00:00 | отслеживается |
| VPS | /opt/kesha-bot/CLAUDE.md | симлинк → /opt/kesha-bot/AGENTS.md | 50698 | aa986e14a4b6181aba611c2888ea4be9761949f562fb22944944cdca95cff980 | 2026-09-20T05:55:37.660513+00:00 | отслеживается |
| ноутбук | /home/maxim/.claude/CLAUDE.md | обычный файл | 26839 | dcfc83a8efa1b2abe5cbacde13f6b3c3ce0602195a1616fd68886931c2ecb04a | 2026-08-23T13:34:46.552097+00:00 | вне репозитория |
| ноутбук | /home/maxim/.claude/mcp-servers/yougile-mcp/CLAUDE.md | обычный файл | 13231 | 6951fb5f9b90abab8cacef552f85965ec9104e55f81f7935b61f9a511f5f77e9 | 2026-02-08T07:22:30.032927+00:00 | отслеживается |
| ноутбук | /home/maxim/.claude/plugins/marketplaces/claude-fortress/CLAUDE.md | обычный файл | 1634 | f65668e8eeaa41cf12fc0e783e48229a9b3cfb7bc45a4de7f49c34c06c3fe81e | 2026-02-17T14:41:30.594501+00:00 | отслеживается |
| ноутбук | /home/maxim/.claude/plugins/marketplaces/ultrapack/CLAUDE.md | обычный файл | 1157 | 4d5411022bb0920576012e5d3dd4000f30b22db23d688d301efd09bfb865337d | 2026-04-17T15:53:33.081172+00:00 | отслеживается |
| ноутбук | /home/maxim/.codex/.tmp/plugins/plugins/build-web-apps/skills/react-best-practices/AGENTS.md | обычный файл | 94496 | 6327efcce0c631580cee5bf2dcac8f884a81172a0261fa3c8ca458a72f603165 | 2026-09-17T05:29:01.116626+00:00 | отслеживается |
| ноутбук | /home/maxim/.codex/.tmp/plugins/plugins/build-web-apps/skills/supabase-best-practices/AGENTS.md | обычный файл | 2160 | bc26c551fda72e50b66e132854aa63ead7280c93b0d1f6bbb6c4f841e7c1202e | 2026-09-17T05:29:01.119455+00:00 | отслеживается |
| ноутбук | /home/maxim/.codex/.tmp/plugins/plugins/data-analytics/AGENTS.md | обычный файл | 2561 | fa92c49b2e5d991383724f4cc1ebf4960840c608603b895602ee60175feb7282 | 2026-09-17T05:29:01.183679+00:00 | отслеживается |
| ноутбук | /home/maxim/.codex/.tmp/plugins/plugins/product-design/templates/mobile-app/AGENTS.md | обычный файл | 10749 | a2790a23f9c65debc9e377512b74635b44c6403c3b4ef6eb72e1a6055ff4cd15 | 2026-09-17T05:29:01.295254+00:00 | отслеживается |
| ноутбук | /home/maxim/.codex/.tmp/plugins/plugins/product-design/templates/prototype/AGENTS.md | обычный файл | 1044 | 4e20d00d0612fe53f04c26b11175879780ae6ba4a4d2245af9599f50e448e505 | 2026-09-17T05:29:01.300057+00:00 | отслеживается |
| ноутбук | /home/maxim/.codex/.tmp/plugins/plugins/vercel/skills/react-best-practices/AGENTS.md | обычный файл | 94347 | 722aa11cb37a6fc3748414c095870e8547b95b370152371272ca2afb8db880f4 | 2026-09-17T05:29:01.402349+00:00 | отслеживается |
| ноутбук | /home/maxim/.codex/.tmp/plugins/plugins/zoom/AGENTS.md | обычный файл | 463 | 41d8bbb7a5d4256c4d31a20844a204df79ab7712d502c90c5f3f8065a838bb6b | 2026-09-17T05:29:01.408524+00:00 | отслеживается |
| ноутбук | /home/maxim/.codex/AGENTS.md | обычный файл | 17021 | b236842809c520879cc44af9e4bfd0be713fe36fc1ef30a05f8d825c709fbe1a | 2026-08-23T12:56:26.962744+00:00 | вне репозитория |
| ноутбук | /mnt/data/Projects/Python/Aperant/CLAUDE.md | обычный файл | 15933 | 78240a5c20a1b9eade143123f3ae91e61379781ee74b2c94306335ddd6d527f6 | 2026-04-03T06:29:01.377222+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/BallisticSim/CLAUDE.md | обычный файл | 5370 | 3daf7c8f99233f807d8632540427fbd860314b62335e805eef8a45832e511585 | 2026-03-12T12:04:16.864495+00:00 | вне репозитория |
| ноутбук | /mnt/data/Projects/Python/Claude-Code-Game-Master/AGENTS.md | обычный файл | 9241 | ca5b50cb54635b112dd94a49ee68221c2a565fb9b0f35146bf4749bbee84e990 | 2026-07-27T14:52:50.558743+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/Claude-Code-Game-Master/CLAUDE.md | обычный файл | 24969 | 28846707097604ffc4b9031bb7e69e686763baf91a2eaada7c7baa90e46b7958 | 2026-09-12T16:33:17.454156+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/Parsing/CLAUDE.md | обычный файл | 21042 | 53e7162d5e1de29d94dc447ad836af9502349004388fc07b5380ecbfb9dc2bf7 | 2026-09-10T07:50:50.288292+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/Parsing/ai-assistants/CLAUDE.md | обычный файл | 22347 | 67f7ad7a6860698489a5a16ae8dc63deb41554cda83cd64e5bcf5806f1fdf7ee | 2026-05-14T11:20:00.045188+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/Parsing/parsing-hub/CLAUDE.md | обычный файл | 28921 | 4d112ef3462c252940bb40168c2c8a1c0e5290dc9cd5499d22228ea6c9459a04 | 2026-05-14T06:25:24.867674+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/Parsing/zahoron-laravel/CLAUDE.md | обычный файл | 20791 | 7caa8c05bed505a8b144fdc04a790e8493df557d97e630bd9bfc92fb81781cec | 2026-05-19T07:20:32.288383+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/Parsing/zahoron-mobile/CLAUDE.md | обычный файл | 20791 | 7caa8c05bed505a8b144fdc04a790e8493df557d97e630bd9bfc92fb81781cec | 2026-05-20T04:54:23.102195+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/Parsing/zahoron-phone/CLAUDE.md | обычный файл | 20791 | 7caa8c05bed505a8b144fdc04a790e8493df557d97e630bd9bfc92fb81781cec | 2026-05-20T04:55:29.930021+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/TradingCryptoBot/CLAUDE.md | обычный файл | 11566 | 473c5b65a7fb6726588f7a319f59132e308d33547c7cafddca9158dd6c6970ad | 2026-09-10T07:50:50.097293+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/VPN-Service/CLAUDE.md | обычный файл | 31244 | 2111e5e18ef9aa75888bc07a767d3fe314f7488b18c304e5d71eb11dbe22bfa6 | 2026-09-10T07:50:50.146292+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/civsim/CLAUDE.md | обычный файл | 8210 | 63235c36942cf8bcbf3c5a135a57577ddb31c43d94e49c5445b9e5347381c074 | 2026-04-14T13:09:52.033440+00:00 | вне репозитория |
| ноутбук | /mnt/data/Projects/Python/claude-server/CLAUDE.md | обычный файл | 4294 | ee8133be37e1ffae82b0babeb71b30c8d690414b56860b355f107e52a668f529 | 2026-04-12T09:04:43.423760+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/games/CLAUDE.md | обычный файл | 6559 | 8ff18028ea836887eedf13cf47c38e05dd6de1213e701f3c88ceba35f3692b49 | 2026-09-19T11:52:00.114407+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/inscryption-ai/CLAUDE.md | обычный файл | 1598 | 15a1f1dfdff1fad69df3b7128123f573b2b1b78bd401d9a31829efb1f31c9b5c | 2026-07-28T06:28:17.077201+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/kesha-tg-bot/CLAUDE.md | обычный файл | 50114 | 77f7e0f72575f40f33495b73f3dd6990e8edc13e32294f2b47c2d835137b8084 | 2026-09-10T07:50:49.837293+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-architecture-audit/AGENTS.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-07T15:45:25.093364+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-architecture-audit/CLAUDE.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-07T15:45:25.095364+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-astra-usage/AGENTS.md | обычный файл | 15950 | c8cc80e8d48bd48ab412b07e0effa2f3d0430575c56dbced61c36fa68aacfcc2 | 2026-09-05T11:49:14.759254+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-astra-usage/CLAUDE.md | обычный файл | 15950 | c8cc80e8d48bd48ab412b07e0effa2f3d0430575c56dbced61c36fa68aacfcc2 | 2026-09-05T11:49:14.760254+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-bash-latency-20260905/AGENTS.md | обычный файл | 16061 | 82f62394f65b0869402b91cb17063a07dc8cdd7ee201acf74d2295fa8e481ec6 | 2026-09-05T11:47:11.924167+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-bash-latency-20260905/CLAUDE.md | обычный файл | 16061 | 82f62394f65b0869402b91cb17063a07dc8cdd7ee201acf74d2295fa8e481ec6 | 2026-09-05T11:47:11.925083+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-codex-state-compat/AGENTS.md | обычный файл | 10954 | dd647395380a90a91ae8393b1b1d2c39640ce057ddef6abd05fdefd2a2f67124 | 2026-09-05T09:40:02.507431+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-codex-state-compat/CLAUDE.md | обычный файл | 139 | 3adae422c0b664693ff97b781bb18674bfb54a55f5fe6c3f20bdbe50898441bf | 2026-09-05T09:40:02.508431+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-day-20260907/AGENTS.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-07T13:06:44.404169+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-day-20260907/CLAUDE.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-07T13:06:44.407169+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-db-research/AGENTS.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-07T15:44:12.874569+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-db-research/CLAUDE.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-07T15:44:12.878569+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-design-gallery/AGENTS.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-07T04:05:31.536777+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-design-gallery/CLAUDE.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-07T04:05:31.539777+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-enterprise/CLAUDE.md | обычный файл | 13902 | a65b61e061f34c21ea5c5406159cb776cfb860f7ca44c1f873ec357d4c3196e9 | 2026-07-03T12:14:48.614075+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-handoff-context-window/AGENTS.md | обычный файл | 15950 | c8cc80e8d48bd48ab412b07e0effa2f3d0430575c56dbced61c36fa68aacfcc2 | 2026-09-05T11:30:34.484251+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-handoff-context-window/CLAUDE.md | обычный файл | 15950 | c8cc80e8d48bd48ab412b07e0effa2f3d0430575c56dbced61c36fa68aacfcc2 | 2026-09-05T11:30:34.525251+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-html-skill/AGENTS.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-07T06:20:11.661827+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-html-skill/CLAUDE.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-07T06:20:11.662827+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-instruction-guard/AGENTS.md | обычный файл | 15950 | c8cc80e8d48bd48ab412b07e0effa2f3d0430575c56dbced61c36fa68aacfcc2 | 2026-09-05T10:07:55.158268+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-instruction-guard/CLAUDE.md | обычный файл | 15950 | c8cc80e8d48bd48ab412b07e0effa2f3d0430575c56dbced61c36fa68aacfcc2 | 2026-09-05T10:07:55.299950+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-knowledge-delivery/AGENTS.md | обычный файл | 10954 | dd647395380a90a91ae8393b1b1d2c39640ce057ddef6abd05fdefd2a2f67124 | 2026-09-05T09:19:58.730441+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-knowledge-delivery/CLAUDE.md | обычный файл | 139 | 3adae422c0b664693ff97b781bb18674bfb54a55f5fe6c3f20bdbe50898441bf | 2026-09-05T09:19:45.918445+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-local-workflow/AGENTS.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-08T02:31:53.340800+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-local-workflow/CLAUDE.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-08T02:31:53.342800+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-model-text-control-flow/AGENTS.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-07T14:04:14.851287+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-model-text-control-flow/CLAUDE.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-07T14:04:14.853287+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-receipt-audit/AGENTS.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-07T04:31:53.917702+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-receipt-audit/CLAUDE.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-07T04:31:53.919703+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-remove-dead-compat/AGENTS.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-08T04:34:43.741835+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-remove-dead-compat/CLAUDE.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-08T04:34:43.744835+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-retire-legacy-review/AGENTS.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-08T04:59:55.919149+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-retire-legacy-review/CLAUDE.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-08T04:59:55.922149+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-service-lifecycle-baseline/AGENTS.md | обычный файл | 16003 | 8324bd7fc3680688714b41a94ca54b72a1728604fe048abbc637cfeae0a00124 | 2026-09-10T05:52:50.972101+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-service-lifecycle-baseline/CLAUDE.md | обычный файл | 16003 | 8324bd7fc3680688714b41a94ca54b72a1728604fe048abbc637cfeae0a00124 | 2026-09-10T05:52:50.972890+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-service-lifecycle/AGENTS.md | обычный файл | 13460 | 7ae258b6917ada7f43d0c48856e73bfe57daf9d2d5b6cf184ba9fca0bfd6255a | 2026-09-10T06:00:11.321167+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-service-lifecycle/CLAUDE.md | обычный файл | 13460 | 7ae258b6917ada7f43d0c48856e73bfe57daf9d2d5b6cf184ba9fca0bfd6255a | 2026-09-10T06:00:11.321167+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-simplify-review/AGENTS.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-07T14:04:09.521302+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-simplify-review/CLAUDE.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-07T14:04:09.525302+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-stability-recovery/CLAUDE.md | обычный файл | 224719 | 298e291c1866285592ca6236a833840fea332c082094d42e4a558faf5c8c1cc7 | 2026-09-05T08:27:06.573644+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-storage-baseline/AGENTS.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-08T05:20:10.006284+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-storage-baseline/CLAUDE.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-08T05:20:10.009284+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-storage/AGENTS.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-08T02:39:36.569749+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-storage/CLAUDE.md | обычный файл | 16065 | 8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44 | 2026-09-08T02:39:36.571749+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-sync-20260912/AGENTS.md | обычный файл | 13460 | 7ae258b6917ada7f43d0c48856e73bfe57daf9d2d5b6cf184ba9fca0bfd6255a | 2026-09-12T15:39:54.969464+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-sync-20260912/CLAUDE.md | обычный файл | 13460 | 7ae258b6917ada7f43d0c48856e73bfe57daf9d2d5b6cf184ba9fca0bfd6255a | 2026-09-12T15:39:54.973464+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-v544-vps-report/AGENTS.md | обычный файл | 13460 | 7ae258b6917ada7f43d0c48856e73bfe57daf9d2d5b6cf184ba9fca0bfd6255a | 2026-09-13T15:01:28.710601+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-v544-vps-report/CLAUDE.md | обычный файл | 13460 | 7ae258b6917ada7f43d0c48856e73bfe57daf9d2d5b6cf184ba9fca0bfd6255a | 2026-09-13T15:01:28.714601+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-worker-autonomy/AGENTS.md | обычный файл | 15950 | c8cc80e8d48bd48ab412b07e0effa2f3d0430575c56dbced61c36fa68aacfcc2 | 2026-09-05T10:51:54.492983+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra-worker-autonomy/CLAUDE.md | обычный файл | 15950 | c8cc80e8d48bd48ab412b07e0effa2f3d0430575c56dbced61c36fa68aacfcc2 | 2026-09-05T10:51:54.493983+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra/AGENTS.md | обычный файл | 12264 | 8c0f0c8e7ba6d79abe7729db08ad4e7f67accd1d5caa0928a72e8548c2aca434 | 2026-09-15T08:43:51.628162+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/orchestra/CLAUDE.md | обычный файл | 12264 | 8c0f0c8e7ba6d79abe7729db08ad4e7f67accd1d5caa0928a72e8548c2aca434 | 2026-09-15T08:43:51.629774+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/seedon/CLAUDE.md | обычный файл | 105499 | 6ea7f2751d264fbee45da379af937aeb8e1b8477491cf0a7d75b6b8360ed3756 | 2026-09-10T07:50:50.235292+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/seedon/infra/CLAUDE.md | обычный файл | 2538 | 253b07a96cf0706f35b5a7393e179073c54be627a112ec6d1f5bb2dbfcceeece | 2026-08-03T07:02:35.212776+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/seedon/site/CLAUDE.md | обычный файл | 9765 | bcda282b28ae53bc51169db856be7807c7ea1c04979daf80713f63b40950edec | 2026-07-23T11:41:22.622284+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Python/slay-the-spire-analysis/CLAUDE.md | обычный файл | 4654 | e1d25e196cd38f1416d3ace49d504c328ba5702d65055f5b96b3684896bc2206 | 2026-04-12T04:54:33.508605+00:00 | вне репозитория |
| ноутбук | /mnt/data/Projects/Python/stargate-tactics/CLAUDE.md | обычный файл | 3334 | 64aa7f4d160c20c5d78f9a22aa694eb68a74dfe692f47e21f14307d763fb4c78 | 2026-06-30T09:58:25.390683+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Unity/AIMedical/CLAUDE.md | обычный файл | 4013 | 9d97af8bc70a6cae9897f7ca19178038fc1872ea8a3fca8f66a4cb7603c5b816 | 2026-02-17T05:37:15.264762+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/Unity/DefaultProjectUnity/CLAUDE.md | обычный файл | 2659 | 4f519bfc391b43c1ee7efa9a5687e014c1752a778121d0bfcead9972787e3b92 | 2026-05-19T05:47:41.381591+00:00 | не отслеживается |
| ноутбук | /mnt/data/Projects/Unity/POLUS/CLAUDE.md | обычный файл | 3950 | 14d7e6a8135694df1e8ac91eca98f21009e17d1c25463118160cd0288eda3609 | 2026-04-09T15:30:43.849255+00:00 | вне репозитория |
| ноутбук | /mnt/data/Projects/Unity/WinterGame/CLAUDE.md | обычный файл | 3811 | bf0a96c8375297ca3f0f6e98dab36494de2302fd10691ea26f0a521f6dee63cb | 2026-02-17T15:39:22.375884+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/University/CLAUDE.md | обычный файл | 12878 | 4a6c99691f9d09e57a2b0cc9b99f7f686b8245262a33f8c4e39fcb8a586f1627 | 2026-09-03T11:26:00.409444+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/cog-second-brain/AGENTS.md | обычный файл | 68285 | 535789f1913a2551c66c2c0c77f9bf68c3dc13107bbbcb41128b8debcfeac8c7 | 2026-09-16T08:26:00.006937+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/cog-second-brain/CLAUDE.md | обычный файл | 100233 | a1b9bbd9a0c6c5a9f6081851065048d12087cae7014439c2daafe190b9c87645 | 2026-09-16T08:26:00.008941+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/cog-second-brain/GEMINI.md | обычный файл | 1996 | d9293f92cc11d8c5df9d0c672227f7ec8df9ff13f5cf98d6e6dd34a274840e7f | 2026-09-16T08:26:00.008941+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/comfy-image-pipeline/AGENTS.md | обычный файл | 15747 | da10c5474342ad189569a69663a8970aaa148544907fade36c83ba43cbad3b75 | 2026-09-10T07:52:11.080648+00:00 | не отслеживается |
| ноутбук | /mnt/data/Projects/comfy-image-pipeline/CLAUDE.md | обычный файл | 86558 | 171ccd9358406988351a08f44046630dfb44c2f82c9efe1a49f4bfd90f29d730 | 2026-09-10T07:51:39.650165+00:00 | отслеживается |
| ноутбук | /mnt/data/Projects/pitch-ball/CLAUDE.md | обычный файл | 5915 | 6110b7cbd548649a6c286e4f612abe901a162bb18a448d851909521dd4f04c45 | 2026-08-29T09:50:55.337597+00:00 | отслеживается |

## Группы дублей по sha256

### Группа 1: `14625f965a41fe649b031a7349fe07598a3bdadaf146a53f75857e085bdbe5ad`

- /home/kesha/.claude/CLAUDE.md
- /home/kesha/.codex/AGENTS.md
### Группа 2: `22885957ac76bb03e923e18d0ee23ccd7cd005124d927cb3b8c483295f7f33ed`

- /home/kesha/ai-table-i1-deploy/app.new/CLAUDE.md
- /home/kesha/projects/ai-table-mvp/CLAUDE.md
- /opt/ai-table-i1/app.previous-20260819T070110Z/CLAUDE.md
- /opt/ai-table-i1/app.previous-20260819T102713Z/CLAUDE.md
- /opt/ai-table-i1/app.previous-20260819T102841Z/CLAUDE.md
- /opt/ai-table-i1/app.previous-20260819T104121Z/CLAUDE.md
- /opt/ai-table-i1/app.previous-20260819T104518Z/CLAUDE.md
- /opt/ai-table-i1/app/CLAUDE.md
### Группа 3: `253b07a96cf0706f35b5a7393e179073c54be627a112ec6d1f5bb2dbfcceeece`

- /home/kesha/projects/seedon/infra/CLAUDE.md
- /mnt/data/Projects/Python/seedon/infra/CLAUDE.md
### Группа 4: `278ae296b7d3dfaf53e2b0d7d859f1211c76346d0103839ce90fb12e683b7d37`

- /opt/cog-second-brain/AGENTS.md
- /opt/cog-second-brain/CLAUDE.md
### Группа 5: `2e78ab1faed823f5ebcfd08de80478fc5efb27c4ed589ad4e4cf6716d5b2c83f`

- /home/kesha/projects/dnd-game-master.rsync-old/AGENTS.md
- /home/kesha/projects/dnd-game-master.rsync-old/CLAUDE.md
### Группа 6: `3adae422c0b664693ff97b781bb18674bfb54a55f5fe6c3f20bdbe50898441bf`

- /mnt/data/Projects/Python/orchestra-codex-state-compat/CLAUDE.md
- /mnt/data/Projects/Python/orchestra-knowledge-delivery/CLAUDE.md
### Группа 7: `7ae258b6917ada7f43d0c48856e73bfe57daf9d2d5b6cf184ba9fca0bfd6255a`

- /mnt/data/Projects/Python/orchestra-service-lifecycle/AGENTS.md
- /mnt/data/Projects/Python/orchestra-service-lifecycle/CLAUDE.md
- /mnt/data/Projects/Python/orchestra-sync-20260912/AGENTS.md
- /mnt/data/Projects/Python/orchestra-sync-20260912/CLAUDE.md
- /mnt/data/Projects/Python/orchestra-v544-vps-report/AGENTS.md
- /mnt/data/Projects/Python/orchestra-v544-vps-report/CLAUDE.md
### Группа 8: `7caa8c05bed505a8b144fdc04a790e8493df557d97e630bd9bfc92fb81781cec`

- /mnt/data/Projects/Python/Parsing/zahoron-laravel/CLAUDE.md
- /mnt/data/Projects/Python/Parsing/zahoron-mobile/CLAUDE.md
- /mnt/data/Projects/Python/Parsing/zahoron-phone/CLAUDE.md
### Группа 9: `82f62394f65b0869402b91cb17063a07dc8cdd7ee201acf74d2295fa8e481ec6`

- /mnt/data/Projects/Python/orchestra-bash-latency-20260905/AGENTS.md
- /mnt/data/Projects/Python/orchestra-bash-latency-20260905/CLAUDE.md
### Группа 10: `8324bd7fc3680688714b41a94ca54b72a1728604fe048abbc637cfeae0a00124`

- /mnt/data/Projects/Python/orchestra-service-lifecycle-baseline/AGENTS.md
- /mnt/data/Projects/Python/orchestra-service-lifecycle-baseline/CLAUDE.md
### Группа 11: `89268bc344d265c691c6d6970ffe60bfc3473c73dcb48513caed43d20259f32a`

- /opt/ai-table-i1/app.previous-20260819T034912Z/CLAUDE.md
- /opt/ai-table-i1/app.previous-20260819T040607Z/CLAUDE.md
- /opt/ai-table-i1/app.previous-20260819T041229Z/CLAUDE.md
- /opt/ai-table-i1/app.previous-20260819T044156Z/CLAUDE.md
### Группа 12: `8ac7443ec10d0fd5425028e239e140811c479a7a65074bec072bd14986867a44`

- /home/kesha/orchestra-storage-deploy/AGENTS.md
- /home/kesha/orchestra-storage-deploy/CLAUDE.md
- /mnt/data/Projects/Python/orchestra-architecture-audit/AGENTS.md
- /mnt/data/Projects/Python/orchestra-architecture-audit/CLAUDE.md
- /mnt/data/Projects/Python/orchestra-day-20260907/AGENTS.md
- /mnt/data/Projects/Python/orchestra-day-20260907/CLAUDE.md
- /mnt/data/Projects/Python/orchestra-db-research/AGENTS.md
- /mnt/data/Projects/Python/orchestra-db-research/CLAUDE.md
- /mnt/data/Projects/Python/orchestra-design-gallery/AGENTS.md
- /mnt/data/Projects/Python/orchestra-design-gallery/CLAUDE.md
- /mnt/data/Projects/Python/orchestra-html-skill/AGENTS.md
- /mnt/data/Projects/Python/orchestra-html-skill/CLAUDE.md
- /mnt/data/Projects/Python/orchestra-local-workflow/AGENTS.md
- /mnt/data/Projects/Python/orchestra-local-workflow/CLAUDE.md
- /mnt/data/Projects/Python/orchestra-model-text-control-flow/AGENTS.md
- /mnt/data/Projects/Python/orchestra-model-text-control-flow/CLAUDE.md
- /mnt/data/Projects/Python/orchestra-receipt-audit/AGENTS.md
- /mnt/data/Projects/Python/orchestra-receipt-audit/CLAUDE.md
- /mnt/data/Projects/Python/orchestra-remove-dead-compat/AGENTS.md
- /mnt/data/Projects/Python/orchestra-remove-dead-compat/CLAUDE.md
- /mnt/data/Projects/Python/orchestra-retire-legacy-review/AGENTS.md
- /mnt/data/Projects/Python/orchestra-retire-legacy-review/CLAUDE.md
- /mnt/data/Projects/Python/orchestra-simplify-review/AGENTS.md
- /mnt/data/Projects/Python/orchestra-simplify-review/CLAUDE.md
- /mnt/data/Projects/Python/orchestra-storage-baseline/AGENTS.md
- /mnt/data/Projects/Python/orchestra-storage-baseline/CLAUDE.md
- /mnt/data/Projects/Python/orchestra-storage/AGENTS.md
- /mnt/data/Projects/Python/orchestra-storage/CLAUDE.md
### Группа 13: `8c0f0c8e7ba6d79abe7729db08ad4e7f67accd1d5caa0928a72e8548c2aca434`

- /mnt/data/Projects/Python/orchestra/AGENTS.md
- /mnt/data/Projects/Python/orchestra/CLAUDE.md
### Группа 14: `aa986e14a4b6181aba611c2888ea4be9761949f562fb22944944cdca95cff980`

- /home/kesha/projects/kesha-tg-bot/CLAUDE.md
- /opt/kesha-bot/AGENTS.md
- /opt/kesha-bot/CLAUDE.md
### Группа 15: `af7272c09fe061e10b215a9a5d1045ce8eb4705435794c5652ddab0ec9a91609`

- /home/kesha/projects/VPN-Service/AGENTS.md
- /home/kesha/projects/VPN-Service/CLAUDE.md
### Группа 16: `bb9556429c43f8d91c8c83f3b1f36d88e94de7492b94fc84f2e446c1aa78c40f`

- /home/kesha/projects/comfy-image-pipeline/AGENTS.md
- /home/kesha/projects/comfy-image-pipeline/CLAUDE.md
- /home/kesha/projects/mfm-2026-infra/CLAUDE.md
- /home/kesha/split/mfm-2026-globe/CLAUDE.md
- /home/kesha/split/mfm-2026-oil-paint/CLAUDE.md
- /home/kesha/split/mfm-2026-photobooth/CLAUDE.md
- /home/kesha/split/mfm-2026-voice/CLAUDE.md
### Группа 17: `c8cc80e8d48bd48ab412b07e0effa2f3d0430575c56dbced61c36fa68aacfcc2`

- /mnt/data/Projects/Python/orchestra-astra-usage/AGENTS.md
- /mnt/data/Projects/Python/orchestra-astra-usage/CLAUDE.md
- /mnt/data/Projects/Python/orchestra-handoff-context-window/AGENTS.md
- /mnt/data/Projects/Python/orchestra-handoff-context-window/CLAUDE.md
- /mnt/data/Projects/Python/orchestra-instruction-guard/AGENTS.md
- /mnt/data/Projects/Python/orchestra-instruction-guard/CLAUDE.md
- /mnt/data/Projects/Python/orchestra-worker-autonomy/AGENTS.md
- /mnt/data/Projects/Python/orchestra-worker-autonomy/CLAUDE.md
### Группа 18: `ca5b50cb54635b112dd94a49ee68221c2a565fb9b0f35146bf4749bbee84e990`

- /home/kesha/projects/dnd-game-master/AGENTS.md
- /mnt/data/Projects/Python/Claude-Code-Game-Master/AGENTS.md
### Группа 19: `d44b08facf18e6ae3f328809d972f248b332397b6f0423fd787136b40264392f`

- /home/kesha/projects/seedon/AGENTS.md
- /home/kesha/projects/seedon/CLAUDE.md
### Группа 20: `d9293f92cc11d8c5df9d0c672227f7ec8df9ff13f5cf98d6e6dd34a274840e7f`

- /opt/cog-second-brain/GEMINI.md
- /mnt/data/Projects/cog-second-brain/GEMINI.md
### Группа 21: `dc520fad8de8a747c0c05e57578cdf247398920899a754dca73bc3b01878f82b`

- /opt/ai-table-i1/app.previous-20260819T044347Z/CLAUDE.md
- /opt/ai-table-i1/app.previous-20260819T053335Z/CLAUDE.md
### Группа 22: `dd647395380a90a91ae8393b1b1d2c39640ce057ddef6abd05fdefd2a2f67124`

- /mnt/data/Projects/Python/orchestra-codex-state-compat/AGENTS.md
- /mnt/data/Projects/Python/orchestra-knowledge-delivery/AGENTS.md
### Группа 23: `e7a39696914fd8f68a2efd7a79b99edbd728bbd68734a89a6395669cb70fd9e3`

- /home/kesha/orchestra/AGENTS.md
- /home/kesha/orchestra/CLAUDE.md
### Группа 24: `fd60465ffdbaec86bad04fa1f302e15a8dfb2a199512c0f3bc17c114f853a46e`

- /home/kesha/bench219/p2-1/CLAUDE.md
- /home/kesha/bench219/p2-2/CLAUDE.md
- /home/kesha/bench219/p2-3/CLAUDE.md
- /home/kesha/bench219/p2-4/CLAUDE.md
- /home/kesha/bench219/p2-5/CLAUDE.md
- /home/kesha/bench219/p2-6/CLAUDE.md
- /home/kesha/bench219/p2-7/CLAUDE.md
- /home/kesha/bench219/p2-8/CLAUDE.md
- /home/kesha/bench219/repo-a/CLAUDE.md
- /home/kesha/bench219/repo-b/CLAUDE.md
### Группа 25: `fe863181ab576423ed523559bef00506b33485036d73cb5e36b03b9a89538ae1`

- /home/kesha/katya-work/AGENTS.md
- /home/kesha/katya-work/CLAUDE.md

## Группы по каталогу

### Группа 1: VPS — `/home/kesha/katya-work`

Файлы: 2; побайтное совпадение всех файлов: да

- `/home/kesha/katya-work/AGENTS.md` ↔ `/home/kesha/katya-work/CLAUDE.md`: побайтно совпадают.
### Группа 2: VPS — `/home/kesha/orchestra`

Файлы: 2; побайтное совпадение всех файлов: да

- `/home/kesha/orchestra/AGENTS.md` ↔ `/home/kesha/orchestra/CLAUDE.md`: побайтно совпадают.
### Группа 3: VPS — `/home/kesha/orchestra-storage-deploy`

Файлы: 2; побайтное совпадение всех файлов: да

- `/home/kesha/orchestra-storage-deploy/AGENTS.md` ↔ `/home/kesha/orchestra-storage-deploy/CLAUDE.md`: побайтно совпадают.
### Группа 4: VPS — `/home/kesha/projects/VPN-Service`

Файлы: 2; побайтное совпадение всех файлов: да

- `/home/kesha/projects/VPN-Service/AGENTS.md` ↔ `/home/kesha/projects/VPN-Service/CLAUDE.md`: побайтно совпадают.
### Группа 5: VPS — `/home/kesha/projects/comfy-image-pipeline`

Файлы: 2; побайтное совпадение всех файлов: да

- `/home/kesha/projects/comfy-image-pipeline/AGENTS.md` ↔ `/home/kesha/projects/comfy-image-pipeline/CLAUDE.md`: побайтно совпадают.
### Группа 6: VPS — `/home/kesha/projects/dnd-game-master`

Файлы: 2; побайтное совпадение всех файлов: нет

- `/home/kesha/projects/dnd-game-master/AGENTS.md` ↔ `/home/kesha/projects/dnd-game-master/CLAUDE.md`: побайтно НЕ совпадают.
```diff
- 1: # DM System - Multi-client and Developer Rules
- 2:
- 3: ## Gameplay adapters (Claude / Codex / Grok Build)
- 4:
- 5: Play uses the same engine (`tools/*.sh`, WorldGraph, `.claude/additional/` rules).
```
### Группа 7: VPS — `/home/kesha/projects/dnd-game-master.rsync-old`

Файлы: 2; побайтное совпадение всех файлов: да

- `/home/kesha/projects/dnd-game-master.rsync-old/AGENTS.md` ↔ `/home/kesha/projects/dnd-game-master.rsync-old/CLAUDE.md`: побайтно совпадают.
### Группа 8: VPS — `/home/kesha/projects/kesha-tg-bot`

Файлы: 2; побайтное совпадение всех файлов: нет

- `/home/kesha/projects/kesha-tg-bot/AGENTS.md` ↔ `/home/kesha/projects/kesha-tg-bot/CLAUDE.md`: побайтно НЕ совпадают.
```diff
- 107: - **Полный сьют гонять на версиях ПРОДА, а не на «самых свежих».** Изолированный прогон (`uv run --isolated --no-project --with-requirements requirements.txt`) обязан нести `--with 'mcp==1.28.1' --with 'claude-agent-sdk==0.2.128'` — ровно то, что стоит в `/opt/kesha-bot/.venv` (сверять `.venv/bin/python -c "import importlib.metadata as m; print(m.version('mcp'))"`). 04.09.2026: `--exclude-newer 2030-01-01` (обход протухшего глобального пина uv) подтянул mcp, где у `Server` больше нет `list_tools` → `kesha_mcp_proxy.py:112` падал на импорте и рушил ВСЮ коллекцию, включая тесты, к зависимости не относящиеся. Это не регрессия задачи: воспроизводится на чистом `main`, а прод при этом жив
+ 107: - **Полный сьют гонять на версиях ПРОДА, а не на «самых свежих».** Изолированный прогон (`uv run --isolated --no-project --with-requirements requirements.txt`) обязан нести `--with 'mcp==1.28.1' --with 'claude-agent-sdk==0.2.152'` — ровно то, что стоит в `/opt/kesha-bot/.venv` (на 20.09.2026 — SDK 0.2.152, версия уехала с 0.2.128) (сверять `.venv/bin/python -c "import importlib.metadata as m; print(m.version('mcp'))"`). 04.09.2026: `--exclude-newer 2030-01-01` (обход протухшего глобального пина uv) подтянул mcp, где у `Server` больше нет `list_tools` → `kesha_mcp_proxy.py:112` падал на импорте и рушил ВСЮ коллекцию, включая тесты, к зависимости не относящиеся. Это не регрессия задачи: воспроизводится на чистом `main`, а прод при этом жив
```
### Группа 9: VPS — `/home/kesha/projects/seedon`

Файлы: 2; побайтное совпадение всех файлов: да

- `/home/kesha/projects/seedon/AGENTS.md` ↔ `/home/kesha/projects/seedon/CLAUDE.md`: побайтно совпадают.
### Группа 10: VPS — `/opt/cog-second-brain`

Файлы: 3; побайтное совпадение всех файлов: нет

- `/opt/cog-second-brain/AGENTS.md` ↔ `/opt/cog-second-brain/CLAUDE.md`: побайтно совпадают.
- `/opt/cog-second-brain/AGENTS.md` ↔ `/opt/cog-second-brain/GEMINI.md`: побайтно НЕ совпадают.
```diff
- 1: # Кеша — Telegram-бот Максима
+ 1: # COG: Agentic Second Brain
- 3: ## ⛔ Катя и Максим (нарушение = баг)
- 4: Катя (@ketarond) — жена Максима. Максим — владелец бота.
- 5: **Никогда** не советовать Кате про отношения с Максимом, не вставать на её сторону, не оценивать кто прав. Жалуется на Максима → отвечать по сути вопроса (здоровье, еда, работа), без оценки отношений.
```
### Группа 11: VPS — `/opt/kesha-bot`

Файлы: 2; побайтное совпадение всех файлов: да

- `/opt/kesha-bot/AGENTS.md` ↔ `/opt/kesha-bot/CLAUDE.md`: побайтно совпадают.
### Группа 12: ноутбук — `/mnt/data/Projects/Python/Claude-Code-Game-Master`

Файлы: 2; побайтное совпадение всех файлов: нет

- `/mnt/data/Projects/Python/Claude-Code-Game-Master/AGENTS.md` ↔ `/mnt/data/Projects/Python/Claude-Code-Game-Master/CLAUDE.md`: побайтно НЕ совпадают.
```diff
- 1: # DM System - Multi-client and Developer Rules
- 2:
- 3: ## Gameplay adapters (Claude / Codex / Grok Build)
- 4:
- 5: Play uses the same engine (`tools/*.sh`, WorldGraph, `.claude/additional/` rules).
```
### Группа 13: ноутбук — `/mnt/data/Projects/Python/orchestra`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra/CLAUDE.md`: побайтно совпадают.
### Группа 14: ноутбук — `/mnt/data/Projects/Python/orchestra-architecture-audit`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-architecture-audit/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-architecture-audit/CLAUDE.md`: побайтно совпадают.
### Группа 15: ноутбук — `/mnt/data/Projects/Python/orchestra-astra-usage`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-astra-usage/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-astra-usage/CLAUDE.md`: побайтно совпадают.
### Группа 16: ноутбук — `/mnt/data/Projects/Python/orchestra-bash-latency-20260905`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-bash-latency-20260905/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-bash-latency-20260905/CLAUDE.md`: побайтно совпадают.
### Группа 17: ноутбук — `/mnt/data/Projects/Python/orchestra-codex-state-compat`

Файлы: 2; побайтное совпадение всех файлов: нет

- `/mnt/data/Projects/Python/orchestra-codex-state-compat/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-codex-state-compat/CLAUDE.md`: побайтно НЕ совпадают.
```diff
- 1: # Orchestra — правила работы
+ 1: @AGENTS.md
- 3: Общий источник правил проекта — этот версионируемый AGENTS.md.
- 4: CLAUDE.md импортирует его для Claude; не создавай вторую копию правил.
- 5: Правила поведения агентов всех проектов принадлежат .orchestra/pipelines/default/prompts/,
```
### Группа 18: ноутбук — `/mnt/data/Projects/Python/orchestra-day-20260907`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-day-20260907/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-day-20260907/CLAUDE.md`: побайтно совпадают.
### Группа 19: ноутбук — `/mnt/data/Projects/Python/orchestra-db-research`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-db-research/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-db-research/CLAUDE.md`: побайтно совпадают.
### Группа 20: ноутбук — `/mnt/data/Projects/Python/orchestra-design-gallery`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-design-gallery/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-design-gallery/CLAUDE.md`: побайтно совпадают.
### Группа 21: ноутбук — `/mnt/data/Projects/Python/orchestra-handoff-context-window`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-handoff-context-window/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-handoff-context-window/CLAUDE.md`: побайтно совпадают.
### Группа 22: ноутбук — `/mnt/data/Projects/Python/orchestra-html-skill`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-html-skill/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-html-skill/CLAUDE.md`: побайтно совпадают.
### Группа 23: ноутбук — `/mnt/data/Projects/Python/orchestra-instruction-guard`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-instruction-guard/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-instruction-guard/CLAUDE.md`: побайтно совпадают.
### Группа 24: ноутбук — `/mnt/data/Projects/Python/orchestra-knowledge-delivery`

Файлы: 2; побайтное совпадение всех файлов: нет

- `/mnt/data/Projects/Python/orchestra-knowledge-delivery/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-knowledge-delivery/CLAUDE.md`: побайтно НЕ совпадают.
```diff
- 1: # Orchestra — правила работы
+ 1: @AGENTS.md
- 3: Общий источник правил проекта — этот версионируемый AGENTS.md.
- 4: CLAUDE.md импортирует его для Claude; не создавай вторую копию правил.
- 5: Правила поведения агентов всех проектов принадлежат .orchestra/pipelines/default/prompts/,
```
### Группа 25: ноутбук — `/mnt/data/Projects/Python/orchestra-local-workflow`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-local-workflow/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-local-workflow/CLAUDE.md`: побайтно совпадают.
### Группа 26: ноутбук — `/mnt/data/Projects/Python/orchestra-model-text-control-flow`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-model-text-control-flow/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-model-text-control-flow/CLAUDE.md`: побайтно совпадают.
### Группа 27: ноутбук — `/mnt/data/Projects/Python/orchestra-receipt-audit`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-receipt-audit/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-receipt-audit/CLAUDE.md`: побайтно совпадают.
### Группа 28: ноутбук — `/mnt/data/Projects/Python/orchestra-remove-dead-compat`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-remove-dead-compat/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-remove-dead-compat/CLAUDE.md`: побайтно совпадают.
### Группа 29: ноутбук — `/mnt/data/Projects/Python/orchestra-retire-legacy-review`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-retire-legacy-review/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-retire-legacy-review/CLAUDE.md`: побайтно совпадают.
### Группа 30: ноутбук — `/mnt/data/Projects/Python/orchestra-service-lifecycle`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-service-lifecycle/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-service-lifecycle/CLAUDE.md`: побайтно совпадают.
### Группа 31: ноутбук — `/mnt/data/Projects/Python/orchestra-service-lifecycle-baseline`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-service-lifecycle-baseline/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-service-lifecycle-baseline/CLAUDE.md`: побайтно совпадают.
### Группа 32: ноутбук — `/mnt/data/Projects/Python/orchestra-simplify-review`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-simplify-review/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-simplify-review/CLAUDE.md`: побайтно совпадают.
### Группа 33: ноутбук — `/mnt/data/Projects/Python/orchestra-storage`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-storage/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-storage/CLAUDE.md`: побайтно совпадают.
### Группа 34: ноутбук — `/mnt/data/Projects/Python/orchestra-storage-baseline`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-storage-baseline/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-storage-baseline/CLAUDE.md`: побайтно совпадают.
### Группа 35: ноутбук — `/mnt/data/Projects/Python/orchestra-sync-20260912`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-sync-20260912/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-sync-20260912/CLAUDE.md`: побайтно совпадают.
### Группа 36: ноутбук — `/mnt/data/Projects/Python/orchestra-v544-vps-report`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-v544-vps-report/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-v544-vps-report/CLAUDE.md`: побайтно совпадают.
### Группа 37: ноутбук — `/mnt/data/Projects/Python/orchestra-worker-autonomy`

Файлы: 2; побайтное совпадение всех файлов: да

- `/mnt/data/Projects/Python/orchestra-worker-autonomy/AGENTS.md` ↔ `/mnt/data/Projects/Python/orchestra-worker-autonomy/CLAUDE.md`: побайтно совпадают.
### Группа 38: ноутбук — `/mnt/data/Projects/cog-second-brain`

Файлы: 3; побайтное совпадение всех файлов: нет

- `/mnt/data/Projects/cog-second-brain/AGENTS.md` ↔ `/mnt/data/Projects/cog-second-brain/CLAUDE.md`: побайтно НЕ совпадают.
```diff
+ 38: - **Задание называет конкретный ключ конфига, флаг или имя поля как факт → проверить его существование в документации ДО записи. Несуществующий не писать «на всякий случай», а вынести в отчёт.** Неизвестный ключ парсер молча игнорирует, и в файле остаётся строка, неотличимая от рабочей настройки, — а автор задания уверен, что настройка применена. 18.08, автосейвы Skyrim: я назвал воркеру `bSaveOnInteriorExteriorSwitch`, ключ оказался из Fallout и в Skyrim не существует (нет ни на STEP-вики, ни в поиске по имени); нужное поведение уже покрывал `bSaveOnTravel=1`. Там же вскрылось второе: у GOG-сборки рабочий ini лежит в `Documents/My Games/Skyrim Special Edition GOG/`, а при `LocalSettings=false` профильную копию MO2 игра не читает вообще — правка «по заданию» не изменила бы ничего. **То же и для артефакта во ВНЕШНЕМ репозитории (файл, квант, тег, версия): проверить существование адресным API-запросом ДО начала работы, отсутствует → взять ближайший аналог с обоснованием, не блокироваться.** Постановщик переносит имя по аналогии с прошлой задачей, а наборы у разных репо расходятся. 19.08: я назвал воркеру квант `IQ4_XS` для Big Talker по аналогии с Dirty Harry — у репо BigTalker IQ-серии нет вообще (репо от 28.11.2024, до IQ-эпохи DavidAU), воркер `paths-info`-запросом это поймал и взял ближайший `Q4_K_S`. Отдельно: скачанный бинарь сверять по SHA256 против `lfs.oid` из HF API — совпадение размера проходит и на битой докачке нужной длины
+ 39: - **Замер идёт на РАЗДЕЛЯЕМОМ ресурсе (GPU, порт, БД, общая машина) → перед каждой пачкой проверять монопольность положительным признаком (ноль чужих потребителей), после — что признак не изменился; разошёлся → пачка БРАК, а не «шум».** Загрязнение читается как правдоподобная цифра, то есть врёт молча. 19.08, замер LFM2.5: на карту посреди пачки встала чужая живая сессия `bigtalker`, раскладка упала со 100% GPU до 48%/52%, числа получились 11–14 t/s вместо 71 — занижение ВПЯТЕРО, и без отбраковки главный вывод («первая модель, влезающая в 4 GB целиком») был бы потерян. Отдельно: **не эмулировать нагрузку на машине, за которой в этот момент работает человек** — в той же задаче CUDA-аллокатор на 1.6 GB отобрал VRAM у пользователя, и его модель уехала на CPU
+ 40: - **Замеряешь эффект правки на НЕДЕТЕРМИНИРОВАННОМ выходе (язык, формат, стиль ответа модели) → гоняй сетку «несколько входов × несколько seed» и публикуй МИНИМУМ и число полных провалов, а не среднее.** Среднее прячет именно тот режим, ради которого правка делалась. 19.08, перевод карточки CraftyCorn: 3 прогона давали 92–100% русского и выглядели как «проблемы нет», полная сетка из 12 вскрыла **4 прогона с НУЛЁМ русского** на английской карточке (разброс 0–100%); после перевода минимум по 12 прогонам — 77%, полных срывов ноль. Там же: замер эффекта карточки надо ставить с тем же системным промптом, что шлёт приложение, — без него разница исчезала полностью, и вывод был бы «правка не нужна»
+ 41: - **Рекомендуешь установку артефакта в конкретный рантайм → сперва проверь, что УСТАНОВЛЕННЫЙ бинарник вообще поддерживает его архитектуру/формат (`strings $(which <rt>) | grep -i <arch>`), и только потом собирай бенчмарки.** Иначе соберёшь доказательства для того, что физически не запустится. 19.08, ревизия моделей: `Nanbeige4.2-3B` имел ЛУЧШИЕ цифры во всём обзоре (GPQA 87.4, SWE-Bench 63.6) — но строки `nanbeige` в бинарнике ollama 0.32.13 нет, в реестре 404. Там же: **`ollama list` показывает размер по тегу, а не по диску** — теги, делящие один блоб (дедупликация), при удалении освобождают 0 GB; реальный мусор ищется как блобы без ссылок из манифестов (нашлось 14.1 GB сирот)
+ 42: - **Ищешь характеристики/бенчмарки локальной модели, названной по ТЕГУ рантайма (ollama, lmstudio, docker) → сперва сверь ревизию по метаданным самого файла, потом ищи карточку.** Тег разъезжается с апстрим-релизом молча, и одноимённая карточка даёт числа другой модели. 19.08, справочник по моделям: тег `qwen3:4b` на диске оказался ревизией **Qwen3-4B-Thinking-2507** (`general.version=2507` в GGUF) с AIME25 **81.3**, тогда как карточка релиза `Qwen/Qwen3-4B` даёт **65.6** — весь блок ушёл бы в vault враньём. Там же: `ollama` наследует прогретую раскладку слоёв, поэтому ОДИНОЧНЫЙ замер t/s врёт (первый прогон дал «занятая карта быстрее свободной» — физически невозможно); каждый замер повторять и писать диапазоном
```
- `/mnt/data/Projects/cog-second-brain/AGENTS.md` ↔ `/mnt/data/Projects/cog-second-brain/GEMINI.md`: побайтно НЕ совпадают.
```diff
- 1: # Кеша — Telegram-бот Максима
+ 1: # COG: Agentic Second Brain
- 3: ## ⛔ Катя и Максим (нарушение = баг)
- 4: Катя (@ketarond) — жена Максима. Максим — владелец бота.
- 5: **Никогда** не советовать Кате про отношения с Максимом, не вставать на её сторону, не оценивать кто прав. Жалуется на Максима → отвечать по сути вопроса (здоровье, еда, работа), без оценки отношений.
```
### Группа 39: ноутбук — `/mnt/data/Projects/comfy-image-pipeline`

Файлы: 2; побайтное совпадение всех файлов: нет

- `/mnt/data/Projects/comfy-image-pipeline/AGENTS.md` ↔ `/mnt/data/Projects/comfy-image-pipeline/CLAUDE.md`: побайтно НЕ совпадают.
```diff
+ 43: - **ПРИОРИТЕТ №1 — рисовалка (общее полотно, `oil-paint/`).** Решение владельца 05.09.2026: «рисовалка это основной проект главный у нас, его надо супер надёжно сделать». При конфликте за исполнителя, время или квоту рисовалка идёт первой. Надёжность здесь важнее скорости выпуска новых экранов в остальных экспонатах. Числовые цели надёжности — задача #109; неизмеренное на сегодня: обрыв питания на Windows, реальное разрешение стены, рост базы за фестивальный день.
- 44: - User authorized autonomous work and both machines. #36/#37/#35 are merged and Windows kiosk services are live on 8217/8233/8787 with Edge external=0/console_errors=0 and real reboot recovery. Terminal gate remains `LIVE_BLOCKED_STYLES_AWAITING_HUMAN`, not product DONE.
- 45: - #22 selected FP8 generator is live: latest resident control `1.810751 s`, reference full warm `1.998432 s`. #28 proves two warm-ups must finish before readiness; after that the internal Q5/P3→AlphaFace→CodeFormer control passed 50/50 within 10 s (p99 `7.027 s`, max `7.188 s`). Public selected-style end-to-end latency is still unmeasured.
+ 45: - User authorized autonomous work and both machines. #36/#37/#35/#45/#46 are merged. SSK-2 runs ComfyUI `8217` and kiosk backend `8787` only: `PhotoboothKioskIdentity` (`8233`) and `PhotoboothTask7Dashboard` (`8765`) are stopped and Disabled permanently by user command 28.08.2026 — identity is not part of the selected cut-first graph. Cold backend task start with both legacy services Disabled: PASS `24.134488 s`, Windows acceptance `SELECTED_STYLES_READY`, `legacy_disabled=true`.
+ 46: - **Public HTTP/entrypoint end-to-end is MEASURED PASS on SSK-2 (#46, 28.08.2026), the first product-path latency in the project.** 50 alternating requests, 25/style, each POST→poll READY→GET final→DELETE: Surikov p50/p95/max `6.063/6.218/6.219 s`, Pozdeev `5.797/6.063/6.094 s`, overall max `6.219 s`, `0/50` over the 10 s gate. Every pre-purge listing was exactly `[final.jpg]`. Evidence `.orchestra/tasks/46/results/public-http-e2e.json`.
```

## Каталоги с перекосом AGENTS.md / CLAUDE.md

### Есть AGENTS.md, нет CLAUDE.md

- VPS: `/home/kesha/.codex`
- ноутбук: `/home/maxim/.codex`
- ноутбук: `/home/maxim/.codex/.tmp/plugins/plugins/build-web-apps/skills/react-best-practices`
- ноутбук: `/home/maxim/.codex/.tmp/plugins/plugins/build-web-apps/skills/supabase-best-practices`
- ноутбук: `/home/maxim/.codex/.tmp/plugins/plugins/data-analytics`
- ноутбук: `/home/maxim/.codex/.tmp/plugins/plugins/product-design/templates/mobile-app`
- ноутбук: `/home/maxim/.codex/.tmp/plugins/plugins/product-design/templates/prototype`
- ноутбук: `/home/maxim/.codex/.tmp/plugins/plugins/vercel/skills/react-best-practices`
- ноутбук: `/home/maxim/.codex/.tmp/plugins/plugins/zoom`

### Есть CLAUDE.md, нет AGENTS.md

- VPS: `/home/kesha/.claude`
- VPS: `/home/kesha/ai-table-i1-deploy/app.new`
- VPS: `/home/kesha/bench219/p2-1`
- VPS: `/home/kesha/bench219/p2-2`
- VPS: `/home/kesha/bench219/p2-3`
- VPS: `/home/kesha/bench219/p2-4`
- VPS: `/home/kesha/bench219/p2-5`
- VPS: `/home/kesha/bench219/p2-6`
- VPS: `/home/kesha/bench219/p2-7`
- VPS: `/home/kesha/bench219/p2-8`
- VPS: `/home/kesha/bench219/repo-a`
- VPS: `/home/kesha/bench219/repo-b`
- VPS: `/home/kesha/orchestra-scratch/237/mini-orchestra`
- VPS: `/home/kesha/projects/University`
- VPS: `/home/kesha/projects/ai-table-mvp`
- VPS: `/home/kesha/projects/mfm-2026-infra`
- VPS: `/home/kesha/projects/seedon/infra`
- VPS: `/home/kesha/split/mfm-2026-globe`
- VPS: `/home/kesha/split/mfm-2026-oil-paint`
- VPS: `/home/kesha/split/mfm-2026-photobooth`
- VPS: `/home/kesha/split/mfm-2026-voice`
- VPS: `/home/kesha/workspace/project`
- VPS: `/opt/ai-table-i1/app`
- VPS: `/opt/ai-table-i1/app.previous-20260819T034912Z`
- VPS: `/opt/ai-table-i1/app.previous-20260819T040607Z`
- VPS: `/opt/ai-table-i1/app.previous-20260819T041229Z`
- VPS: `/opt/ai-table-i1/app.previous-20260819T044156Z`
- VPS: `/opt/ai-table-i1/app.previous-20260819T044347Z`
- VPS: `/opt/ai-table-i1/app.previous-20260819T053335Z`
- VPS: `/opt/ai-table-i1/app.previous-20260819T065231Z`
- VPS: `/opt/ai-table-i1/app.previous-20260819T070110Z`
- VPS: `/opt/ai-table-i1/app.previous-20260819T102713Z`
- VPS: `/opt/ai-table-i1/app.previous-20260819T102841Z`
- VPS: `/opt/ai-table-i1/app.previous-20260819T104121Z`
- VPS: `/opt/ai-table-i1/app.previous-20260819T104518Z`
- ноутбук: `/home/maxim/.claude`
- ноутбук: `/home/maxim/.claude/mcp-servers/yougile-mcp`
- ноутбук: `/home/maxim/.claude/plugins/marketplaces/claude-fortress`
- ноутбук: `/home/maxim/.claude/plugins/marketplaces/ultrapack`
- ноутбук: `/mnt/data/Projects/Python/Aperant`
- ноутбук: `/mnt/data/Projects/Python/BallisticSim`
- ноутбук: `/mnt/data/Projects/Python/Parsing`
- ноутбук: `/mnt/data/Projects/Python/Parsing/ai-assistants`
- ноутбук: `/mnt/data/Projects/Python/Parsing/parsing-hub`
- ноутбук: `/mnt/data/Projects/Python/Parsing/zahoron-laravel`
- ноутбук: `/mnt/data/Projects/Python/Parsing/zahoron-mobile`
- ноутбук: `/mnt/data/Projects/Python/Parsing/zahoron-phone`
- ноутбук: `/mnt/data/Projects/Python/TradingCryptoBot`
- ноутбук: `/mnt/data/Projects/Python/VPN-Service`
- ноутбук: `/mnt/data/Projects/Python/civsim`
- ноутбук: `/mnt/data/Projects/Python/claude-server`
- ноутбук: `/mnt/data/Projects/Python/games`
- ноутбук: `/mnt/data/Projects/Python/inscryption-ai`
- ноутбук: `/mnt/data/Projects/Python/kesha-tg-bot`
- ноутбук: `/mnt/data/Projects/Python/orchestra-enterprise`
- ноутбук: `/mnt/data/Projects/Python/orchestra-stability-recovery`
- ноутбук: `/mnt/data/Projects/Python/seedon`
- ноутбук: `/mnt/data/Projects/Python/seedon/infra`
- ноутбук: `/mnt/data/Projects/Python/seedon/site`
- ноутбук: `/mnt/data/Projects/Python/slay-the-spire-analysis`
- ноутбук: `/mnt/data/Projects/Python/stargate-tactics`
- ноутбук: `/mnt/data/Projects/Unity/AIMedical`
- ноутбук: `/mnt/data/Projects/Unity/DefaultProjectUnity`
- ноутбук: `/mnt/data/Projects/Unity/POLUS`
- ноутбук: `/mnt/data/Projects/Unity/WinterGame`
- ноутбук: `/mnt/data/Projects/University`
- ноутбук: `/mnt/data/Projects/pitch-ball`
