# V-1310 Codex Standard and Fast

The composer selects the speed for new native turns of one local Codex chat. It persists the preference independently of the native thread and of other chats. The app-server receives the turn-level override as documented for CLI 0.169.0. Steering leaves the active turn's speed and usage pricing intact.

Each priced turn retains its observed tokens, requested speed and estimated API cost. Fast applies the published 2× API rates to the same tokens. Subscription consumption on Sol and Astra is weighted 2×, while Terra and Luna are weighted 2.5×. Subscription allowance and virtual API costs remain separate.

Verification included API authentication and persistence, additive migration, steering, token pricing and usage records, and Chromium at 390 and 1280 px. Two existing assertions are excluded from the focused suite after reproducing them at the baseline: the live proxy overrides a test's unscoped proxy, and the stale quota assertion assumes a 300-second cache lifetime. Existing Tailwind-generated CSS drift also reproduced at baseline, with identical newly generated output in the feature checkout.

Focused suite: 228 passed, two baseline assertions deselected. After final presentation and fixture tweaks the six new tests passed again.

Guarded CLI smoke: both Fast and Standard requests completed with 'ok' using ChatGPT authentication in the same isolated thread, with Standard after reattaching to it. The provider did not report a per-turn speed in the rollout. The installed release's source applies the override to the turn copy and tests that an explicit Standard turn does not inherit Fast. The dashboard's dollar values are estimates from the recorded token counts and requested speed.

Sources:
- https://learn.chatgpt.com/docs/pricing#speed-multipliers
- https://developers.openai.com/api/docs/models/gpt-6.2-sol
- https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/core/src/session/turn_context.rs#L1193-L1219
