# Native Codex usage for the KB refactor

Source: the native rollout for thread 01a02d85-5efd-74d2-a96e-bf34cb1aef06.
Only allowlisted counters and closed task IDs were exported; no prompts or private log
contents are copied. Duplicate cumulative snapshots are ignored (2 in the selected turns),
and each nonduplicate cumulative delta is checked against last_token_usage.
reasoning_output_tokens is included in output_tokens, not charged twice.

| Scope | Duration | Usage-bearing responses | Input | Cached input | Fresh input | Output |
|---|---:|---:|---:|---:|---:|---:|
| KB implementation, 15:45–16:17 Krasnoyarsk | 32m08s | 48 | 21631366 | 21341056 | 290310 | 57641 |
| Explicit merge, 16:19–16:21 | 2m30s | 11 | 5562485 | 5548928 | 13557 | 4941 |

CLI settings record priority/Fast. Implementation cache-hit ratio is 98.66%.
The millions of input tokens are repeated context across calls, not unique new data.

Using Orchestra's existing FLAT STANDARD API-equivalent formula (10/1/50 dollars per
million fresh/cached/output tokens): implementation $27.126206, merge $5.931548.
Eight separately recorded Astra evaluation calls add $3.452744: 433184 input,
134144 cached input and 6564 output tokens. Accounted subtotal: $36.510498 in that
display convention, NOT cash expenditure or an exact API invoice. In particular,
this convention omits API Fast and long-context multipliers.

Using the published Codex Astra rates (250/25/1250 credits per million) and 2.5x Fast
for the main session gives an ESTIMATE of 1695.39 credits for implementation and 370.72
for merge. It is not an observed account debit or a measured percentage of weekly quota.
Source: https://learn.chatgpt.com/docs/pricing and
https://learn.chatgpt.com/docs/agent-configuration/speed (checked 05.09.2026).

Limits: this scope excludes preceding research/planning and subsequent conversation.
The native-loader probes and an aborted replay did not retain complete usage receipts,
so the overall cost of every supporting action cannot be reconstructed exactly here.
No claim of a complete account-wide bill or subscription utilization is made.

The statement that interactive usage was "not recorded" is false: native token counters
exist even when Orchestra has no turn_usage row. The stronger statement that AGENTS.md
was the most expensive input is NOT established: the counters do not attribute tokens
to individual files and also include chat history, tool schemas and tool outputs.
Input is 89.4% of the implementation's flat cost, but that is not an AGENTS.md share.
There is no matched Sol execution of this same job, so these numbers cannot prove that
Astra was cheaper or better than Sol for it.
