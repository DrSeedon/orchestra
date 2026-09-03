# #240 measurement table

All model rows used CLI 0.149.0, `gpt-5.6-sol`, `xhigh`, `service_tier=default`, the same cwd, 60-byte task, proxy `http://127.0.0.1:12339`, and zero tool rounds. `system` means Orchestra's extra `developerInstructions`, not Codex's common internal prompt.

Time origins: A `final wall` starts at process launch; B–F `final wall` starts at `turn/start`. `total-to-final` is comparable: A final wall, B–F connect + final wall.

| arm/rep | argv sha256 | config sha256 | bytes input/system/doc/MCP/history-source | connect / ack / TTFT / final wall / total-to-final, s | tokens input/cached/output/reasoning | loadavg | outcome |
|---|---|---|---:|---:|---:|---:|---|
| A_exec/5 | `7c4780bad75d03d1890876df4e011eaf172fcbf5eb80c84e08c0955a578822e4` | `82dfa5b1c5cceb63df37a59b7a27827bfac577a667baa41cf87634f9d8e44c06` | 60/0/104615/0/0 | — / 1.804 / 12.643 / 12.678 / 12.678 | 37490/9984/6/— | 1.09/1.7/2.28 | completed |
| B_appserver/5 | `4d721d35f354d825164b9ee9865f8cde710cbd5d3b802af7f87f43858270cfac` | `82dfa5b1c5cceb63df37a59b7a27827bfac577a667baa41cf87634f9d8e44c06` | 60/0/104615/0/0 | 1.969 / 0.007 / 10.663 / 10.979 / 12.948 | 38056/11008/6/0 | 1.51/1.76/2.29 | completed |
| A_exec/6 | `7c4780bad75d03d1890876df4e011eaf172fcbf5eb80c84e08c0955a578822e4` | `82dfa5b1c5cceb63df37a59b7a27827bfac577a667baa41cf87634f9d8e44c06` | 60/0/104615/0/0 | — / 1.752 / 10.733 / 10.735 / 10.735 | 37480/9984/6/— | 1.72/1.81/2.3 | completed |
| B_appserver/6 | `4d721d35f354d825164b9ee9865f8cde710cbd5d3b802af7f87f43858270cfac` | `82dfa5b1c5cceb63df37a59b7a27827bfac577a667baa41cf87634f9d8e44c06` | 60/0/104615/0/0 | 1.856 / 0.006 / 9.180 / 9.634 / 11.490 | 38051/11008/6/0 | 1.8/1.82/2.29 | completed |
| C_wrapper/1 | `7ae684ace244c1598d35f6c6acba6fb12fff61a683aaec4c6637f1bbc1e18696` | `82dfa5b1c5cceb63df37a59b7a27827bfac577a667baa41cf87634f9d8e44c06` | 60/0/104615/0/0 | 1.293 / 0.007 / 6.592 / 6.715 / 8.008 | 38031/—/6/— | 2.31/2.68/2.81 | completed |
| D_managed_full/1 | `7ae684ace244c1598d35f6c6acba6fb12fff61a683aaec4c6637f1bbc1e18696` | `371322d795a0310cc5ab3722f71ac80efcad1d880295bf47258d293f16cbcea8` | 60/58188/104615/32634/0 | 1.485 / 0.010 / 6.573 / 6.727 / 8.212 | 51602/—/6/— | 2.21/2.65/2.8 | completed |
| E_warm_resume/1 | `7ae684ace244c1598d35f6c6acba6fb12fff61a683aaec4c6637f1bbc1e18696` | `3ee74e0780826559a79580533ffec0308cf90f606cae4e7e35671cae5db54274` | 60/58188/104615/32634/0 | 1.375 / 0.020 / 10.506 / 10.997 / 12.373 | 54558/—/6/— | 2.25/2.65/2.79 | completed |
| C_wrapper/2 | `7ae684ace244c1598d35f6c6acba6fb12fff61a683aaec4c6637f1bbc1e18696` | `82dfa5b1c5cceb63df37a59b7a27827bfac577a667baa41cf87634f9d8e44c06` | 60/0/104615/0/0 | 1.526 / 0.008 / 8.814 / 8.932 / 10.458 | 38036/—/6/— | 2.82/2.76/2.83 | completed |
| D_managed_full/2 | `7ae684ace244c1598d35f6c6acba6fb12fff61a683aaec4c6637f1bbc1e18696` | `fb4c55cfb49b4357bda117d7f5b14285b13c522598f68ece2f644b84ad6f0d8c` | 60/58188/104615/32634/0 | 1.589 / 0.008 / 8.256 / 8.348 / 9.937 | 51612/—/6/— | 3.01/2.8/2.84 | completed |
| E_warm_resume/2 | `7ae684ace244c1598d35f6c6acba6fb12fff61a683aaec4c6637f1bbc1e18696` | `66f64d86a585ded69fa809797668aa0a6fafee8087a20d2b17e6030c27bb6ddd` | 60/58188/104615/32634/0 | 1.602 / 0.014 / 9.078 / 9.140 / 10.743 | 54563/—/6/— | 3.02/2.81/2.84 | completed |
| C_wrapper/3 | `7ae684ace244c1598d35f6c6acba6fb12fff61a683aaec4c6637f1bbc1e18696` | `82dfa5b1c5cceb63df37a59b7a27827bfac577a667baa41cf87634f9d8e44c06` | 60/0/104615/0/0 | 1.878 / 0.009 / 8.005 / 8.055 / 9.933 | 38046/11008/6/— | 1.86/2.55/2.75 | completed |
| D_managed_full/3 | `7ae684ace244c1598d35f6c6acba6fb12fff61a683aaec4c6637f1bbc1e18696` | `4b5ad98908ffad0d73dd56e50e46e45a78459298e2dfe88042fbbc5555ab9f49` | 60/58188/104615/32634/0 | 2.039 / 0.011 / 9.152 / 9.327 / 11.366 | 51627/11008/6/— | 1.96/2.54/2.75 | completed |
| E_warm_resume/3 | `7ae684ace244c1598d35f6c6acba6fb12fff61a683aaec4c6637f1bbc1e18696` | `7feb5f3a2afbbf2f179d2c0fb34ac67dd2917623e3040a615533c22228206137` | 60/58188/104615/32634/0 | 1.599 / 0.016 / 9.049 / 9.160 / 10.759 | 54598/50944/6/— | 1.96/2.53/2.74 | completed |
| F_no_role_prompt/1 | `7ae684ace244c1598d35f6c6acba6fb12fff61a683aaec4c6637f1bbc1e18696` | `242ce086cababbef8bfe5ecdb7a5acd6adf3c137d0738b3e072e152c11c289b1` | 60/0/104615/32634/0 | 1.727 / 0.008 / 6.771 / 6.838 / 8.565 | 38121/—/6/— | 3.29/2.88/2.86 | completed |
| F_no_project_doc/1 | `7ae684ace244c1598d35f6c6acba6fb12fff61a683aaec4c6637f1bbc1e18696` | `f67e9bd890b10e134d8746c6e2314dd6abc219a5642ce6346fa009f03a065994` | 60/58188/0/32634/0 | 1.426 / 0.021 / 7.101 / 7.284 / 8.710 | 30116/—/6/— | 3.54/2.95/2.89 | completed |
| F_no_mcp/1 | `7ae684ace244c1598d35f6c6acba6fb12fff61a683aaec4c6637f1bbc1e18696` | `82dfa5b1c5cceb63df37a59b7a27827bfac577a667baa41cf87634f9d8e44c06` | 60/58188/104615/0/0 | 1.579 / 0.008 / 8.660 / 8.868 / 10.447 | 51537/—/6/— | 3.38/2.93/2.88 | completed |
| F_no_role_prompt/2 | `7ae684ace244c1598d35f6c6acba6fb12fff61a683aaec4c6637f1bbc1e18696` | `9378489e1a93fc4afef31f131ed80d6c9b61ffcf8f38ff8d373f2ad4d934d201` | 60/0/104615/32634/0 | 1.971 / 0.009 / 13.855 / 13.901 / 15.873 | 38146/11008/6/— | 2.12/2.54/2.74 | completed |
| F_no_project_doc/2 | `7ae684ace244c1598d35f6c6acba6fb12fff61a683aaec4c6637f1bbc1e18696` | `31587b54663a2d6a389ec1788138462d0d6ce764ce62bb9968477970f0ff04ec` | 60/58188/0/32634/0 | 1.601 / 0.010 / 14.169 / 14.307 / 15.908 | 30141/11008/6/— | 1.92/2.48/2.72 | completed |
| F_no_mcp/2 | `7ae684ace244c1598d35f6c6acba6fb12fff61a683aaec4c6637f1bbc1e18696` | `82dfa5b1c5cceb63df37a59b7a27827bfac577a667baa41cf87634f9d8e44c06` | 60/58188/104615/0/0 | 1.645 / 0.012 / 7.748 / 7.833 / 9.477 | 51562/11008/6/— | 2.28/2.53/2.73 | completed |
| E_real_archived_history/1 | `7ae684ace244c1598d35f6c6acba6fb12fff61a683aaec4c6637f1bbc1e18696` | `4dbeb1ac9d98555ad51be84c33c97efd22518d2efba9411fdb7f9789bf69c91e` | 60/58188/104615/32634/1370598 | 2.638 / 0.015 / 9.948 / 10.071 / 12.709 | 218468/11008/6/— | 2.99/2.74/2.78 | completed |

## Exact argv catalog

`7c4780bad75d03d1890876df4e011eaf172fcbf5eb80c84e08c0955a578822e4`

```json
["/home/maxim/.local/bin/codex", "exec", "--json", "--ephemeral", "--skip-git-repo-check", "-C", "/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/research-codex-latency", "-s", "danger-full-access", "-m", "gpt-5.6-sol", "-c", "model_reasoning_effort=\"xhigh\"", "-c", "service_tier=\"default\"", "Reply with exactly PONG and nothing else. Do not call tools."]
```

`4d721d35f354d825164b9ee9865f8cde710cbd5d3b802af7f87f43858270cfac`

```json
["/home/maxim/.local/bin/codex", "app-server", "--stdio"]
```

`7ae684ace244c1598d35f6c6acba6fb12fff61a683aaec4c6637f1bbc1e18696`

```json
["/home/maxim/.local/bin/codex", "-c", "model_reasoning_effort=\"xhigh\"", "-c", "features.multi_agent=false", "-c", "web_search=\"live\"", "app-server", "--stdio"]
```

## No-model controls

- Local Python JSON-RPC stdio echo: n=200, median=0.058461 ms, p95=0.087006 ms, max=20.155034 ms, load=2.14/2.67/2.81.
- Empty-home app-server initialize + thread/start: 1.334121 s, outcome=no_model_ok, load=3.01/2.87/2.86.
- Config digest rep 1: unchanged=0.001236 s; forced reconnect=0.452008 s; initial connect=1.937762 s; load=5.78/3.27/2.94.
- Config digest rep 2: unchanged=0.001514 s; forced reconnect=0.498941 s; initial connect=1.508402 s; load=5.64/3.28/2.95.
- MCP positive control: startup notifications contain Orchestra `ready`; mcpServerStatus/list returned 41 Orchestra tools, expected=41, missing=0.
