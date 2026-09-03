# #249 Phase 1 — Gemini CLI primary-source matrix

Retrieval date: 2026-08-13. Scope: official Google and `google-gemini/gemini-cli` primary sources only. This artifact records source evidence and gaps; it contains no recommendation.

## Source matrix

| claim_id | exact_question | source_url_opened | source_type (official-doc / official-source / official-terms) | version_or_retrieval_date | exact_evidence (до 25 слов) | supports | contradicts_or_gap |
|---|---|---|---|---|---|---|---|
| A1-1 | A1 OAuth личного аккаунта без API key | https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/README.md | official-source | `main` at `1ac3377395868295e128b96726d605a900b5946b`; retrieved 2026-08-13 | “No API key management - just sign in with your Google account” | Repository README explicitly describes Google-account OAuth without API-key management. | Contradicted for consumer accounts by A1-2, an official deprecation page updated after the README content remained in `main`. |
| A1-2 | A1 OAuth личного аккаунта без API key | https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals?hl=en | official-doc | Last updated 2026-06-23; retrieved 2026-08-13 | “you can no longer use the Login with Google option to access the IDE extensions or Gemini CLI.” | Current consumer-account shutdown semantics for Google Login. | Contradicts A1-1 and A1-3 for personal/AI Pro/Ultra accounts; Standard/Enterprise access is explicitly unchanged on the same page. |
| A1-3 | A1 OAuth личного аккаунта без API key | https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/docs/get-started/authentication.mdx | official-source | `main` at `1ac3377395868295e128b96726d605a900b5946b`; retrieved 2026-08-13 | “Headless mode will use your existing authentication method, if an existing authentication credential is cached.” | Repository documentation describes reuse of an already cached credential in headless mode. | It does not say a new headless personal OAuth login can be created; A1-2 says consumer Google Login is no longer usable. |
| A2-1 | A2 какие модели Gemini CLI даёт Google-login сейчас | https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/README.md | official-source | `main` at `1ac3377395868295e128b96726d605a900b5946b`; retrieved 2026-08-13 | “Gemini 3 models with 1M token context window” | README associates Google Login with the Gemini 3 model family. | A2-5 says consumer Google Login no longer accesses Gemini CLI; the README does not enumerate exact routed model IDs. |
| A2-2 | A2 какие модели Gemini CLI даёт Google-login сейчас | https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/docs/get-started/gemini-3.md | official-source | `main` at `1ac3377395868295e128b96726d605a900b5946b`; retrieved 2026-08-13 | “Gemini 3.1 Pro Preview is rolling out.” | Conditional availability of `gemini-3.1-pro-preview`; the document says `/model` reveals account access. | It is a rollout statement, not a Google-login entitlement; A2-5 disables consumer Google Login. |
| A2-3 | A2 какие модели Gemini CLI даёт Google-login сейчас | https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/docs/get-started/gemini-3.md | official-source | `main` at `1ac3377395868295e128b96726d605a900b5946b`; retrieved 2026-08-13 | “For simple prompts, it will automatically use Gemini 2.5 Flash.” | Model-routing documentation identifies the simple-prompt fallback/model. | It describes routing generally, not current personal Google-login access. |
| A2-4 | A2 какие модели Gemini CLI даёт Google-login сейчас | https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/docs/get-started/gemini-3.md | official-source | `main` at `1ac3377395868295e128b96726d605a900b5946b`; retrieved 2026-08-13 | “if Gemini 3 Pro is enabled, it will use Gemini 3 Pro; otherwise, it will use Gemini 2.5 Pro.” | Model-routing documentation identifies the complex-prompt primary and fallback models. | Conditional on enablement; it does not bind these models to current consumer Google Login. |
| A2-5 | A2 какие модели Gemini CLI даёт Google-login сейчас | https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals?hl=en | official-doc | Last updated 2026-06-23; retrieved 2026-08-13 | “This also applies to usage of Gemini CLI.” | Extends the consumer-tier request shutdown to Gemini CLI. | Leaves no current personal/AI Pro/Ultra Google-login model entitlement; contradicts still-published A2-1 through A2-4 when read as consumer access. |
| A3-1 | A3 бесплатные CLI/Code Assist лимиты | https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/README.md | official-source | `main` at `1ac3377395868295e128b96726d605a900b5946b`; retrieved 2026-08-13 | “Free tier: 60 requests/min and 1,000 requests/day” | README’s published free consumer limits. | A3-3 says the consumer tier stopped serving requests on 2026-06-18. |
| A3-2 | A3 бесплатные CLI/Code Assist лимиты | https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/docs/resources/quota-and-pricing.md | official-source | `main` at `1ac3377395868295e128b96726d605a900b5946b`; retrieved 2026-08-13 | “1000 maximum model requests / user / day” | Repository quota page’s published free Google-account daily limit. | No numeric per-minute limit on this page; A3-3 says consumer requests stopped. |
| A3-3 | A3 бесплатные CLI/Code Assist лимиты | https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals?hl=en | official-doc | Last updated 2026-06-23; retrieved 2026-08-13 | “Gemini Code Assist IDE extensions stopped serving requests for the Gemini Code Assist for individuals, Google AI Pro, and Google AI Ultra tiers.” | Current shutdown state of the free consumer tier. | Contradicts the still-present numeric consumer limits in A3-1 and A3-2 as current usable quotas. |
| A4-1 | A4 повышенные лимиты retail Google AI Pro/Ultra | https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/docs/resources/quota-and-pricing.md | official-source | `main` at `1ac3377395868295e128b96726d605a900b5946b`; retrieved 2026-08-13 | “Google AI Pro” / “1,500 requests” | Repository quota table’s published personal Google AI Pro daily maximum. | A4-5 says Pro consumer requests stopped; this source does not distinguish retail from partner-provisioned Pro. |
| A4-2 | A4 повышенные лимиты retail Google AI Pro/Ultra | https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/docs/resources/quota-and-pricing.md | official-source | `main` at `1ac3377395868295e128b96726d605a900b5946b`; retrieved 2026-08-13 | “Google AI Ultra” / “2,000 requests” | Repository quota table’s published personal Google AI Ultra daily maximum. | A4-5 says Ultra consumer requests stopped. |
| A4-3 | A4 повышенные лимиты retail Google AI Pro/Ultra | https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/docs/resources/faq.md | official-source | `main` at `1ac3377395868295e128b96726d605a900b5946b`; retrieved 2026-08-13 | “The higher limits in your Google AI Pro or Ultra subscription are for Gemini 2.5 across both Gemini 2.5 Pro and Flash.” | Repository FAQ scopes the advertised higher limits to the Gemini 2.5 Pro/Flash shared pool. | Does not state a higher Gemini 3 quota; A4-5 says consumer access stopped. |
| A4-4 | A4 повышенные лимиты retail Google AI Pro/Ultra | https://docs.cloud.google.com/gemini/docs/quotas?hl=en | official-doc | Last updated 2026-07-29; retrieved 2026-08-13 | “Maximum requests per user per day” / “Standard” / “1500” / “Enterprise” / “2000” | Current official Gemini CLI/agent-mode quota table lists Standard and Enterprise only. | Consumer Free/Pro/Ultra rows are absent; consistent with A4-5 and inconsistent with A4-1/A4-2 as current quotas. |
| A4-5 | A4 повышенные лимиты retail Google AI Pro/Ultra | https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals?hl=en | official-doc | Last updated 2026-06-23; retrieved 2026-08-13 | “Starting June 18, 2026, Gemini Code Assist IDE extensions stopped serving requests” | Shutdown date and state for Google AI Pro/Ultra consumer access. | Numeric 1,500/2,000 entries remain in repository docs but are not current consumer service limits. |
| A5-1 | A5 входит ли Jio-offer в повышенные CLI/Code Assist лимиты | https://blog.google/intl/en-in/company-news/partnering-with-reliance-to-bring-the-best-of-google-ai-to-more-people-across-india/ | official-doc | Published 2025-10-30; retrieved 2026-08-13 | “to offer Google’s AI Pro plan, and with it the latest version of Google Gemini, to Jio Unlimited 5G plan users” | Google calls the Jio benefit a Google AI Pro plan. | The source does not name Gemini CLI or Code Assist; generic Pro wording is insufficient to transfer a retail CLI entitlement. |
| A5-2 | A5 входит ли Jio-offer в повышенные CLI/Code Assist лимиты | https://blog.google/intl/en-in/company-news/partnering-with-reliance-to-bring-the-best-of-google-ai-to-more-people-across-india/ | official-doc | Published 2025-10-30; retrieved 2026-08-13 | “Eligible Jio customers will gain higher access to our most capable Gemini 2.5 Pro model in the Gemini app” | The explicitly named model benefit is in the Gemini app. | `Gemini CLI` and `Code Assist` each have zero matches in the opened article; CLI entitlement remains unestablished. |
| A5-GAP | A5 входит ли Jio-offer в повышенные CLI/Code Assist лимиты | Checked: https://blog.google/intl/en-in/company-news/partnering-with-reliance-to-bring-the-best-of-google-ai-to-more-people-across-india/ ; https://geminicli.com/docs/resources/faq/ ; https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals?hl=en | official-doc | Searched/opened 2026-08-13 | GAP — no opened Google source explicitly joins the Jio offer to Gemini CLI or Code Assist. | No direct entitlement evidence. | Queries checked: `site:blog.google Jio "Gemini CLI"`; `site:support.google.com/googleone Jio "Code Assist"`; `site:developers.google.com Jio "Gemini CLI"`. Generic Pro docs also conflict with the consumer shutdown. |
| A5-3 | A5 входит ли Jio-offer в повышенные CLI/Code Assist лимиты | https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals?hl=en | official-doc | Last updated 2026-06-23; retrieved 2026-08-13 | “stopped serving requests for the Gemini Code Assist for individuals, Google AI Pro, and Google AI Ultra tiers.” | Current service state applies to all named consumer AI Pro tiers without a Jio exception. | No Jio-specific exception is documented on the opened page. |
| A6-1 | A6 ограничения eligibility/account/region/offer cancellation relevant к Jio | https://blog.google/intl/en-in/company-news/partnering-with-reliance-to-bring-the-best-of-google-ai-to-more-people-across-india/ | official-doc | Published 2025-10-30; retrieved 2026-08-13 | “Jio Unlimited 5G plan users at no extra cost for 18 months.” | Plan type and offer duration. | Does not specify ongoing mobile-plan conditions or cancellation triggers. |
| A6-2 | A6 ограничения eligibility/account/region/offer cancellation relevant к Jio | https://blog.google/intl/en-in/company-news/partnering-with-reliance-to-bring-the-best-of-google-ai-to-more-people-across-india/ | official-doc | Published 2025-10-30; retrieved 2026-08-13 | “This offer will begin rolling out to users between 18 to 25 years of age” | Initial age rollout. | The same sentence says it would later extend to every eligible Jio user; it does not define “eligible.” |
| A6-3 | A6 ограничения eligibility/account/region/offer cancellation relevant к Jio | https://blog.google/intl/en-in/company-news/partnering-with-reliance-to-bring-the-best-of-google-ai-to-more-people-across-india/ | official-doc | Published 2025-10-30; retrieved 2026-08-13 | “Eligible Jio users can activate this offer via the MyJio app.” | Jio-controlled activation channel. | No gift-link transferability or resale permission is stated. |
| A6-3R | A6 ограничения eligibility/account/region/offer cancellation relevant к Jio | https://blog.google/company-news/inside-google/around-the-globe/google-asia/reliance-jio-india-partnership/ | official-doc | Published 2025-10-30; retrieved 2026-08-13 | “Eligible users in India can activate the offer through the MyJio app.” | Explicit India-region and MyJio activation statement. | Does not state whether account region, physical location, or both are tested. |
| A6-4 | A6 ограничения eligibility/account/region/offer cancellation relevant к Jio | https://support.google.com/googleone/answer/15801606?hl=en | official-doc | Retrieved 2026-08-13 | “To activate your Google One subscription, you need a personal Google Account.” | Account type required for third-party Google One activation. | General partner-subscription documentation, not Jio-specific eligibility. |
| A6-5 | A6 ограничения eligibility/account/region/offer cancellation relevant к Jio | https://support.google.com/googleone/answer/15801606?hl=en | official-doc | Retrieved 2026-08-13 | “Your current plan may be canceled immediately or continue until the end of the billing cycle based on your provider’s policies.” | General third-party provider cancellation timing. | The exact Jio policy is outside this Google page. |
| A6-6 | A6 ограничения eligibility/account/region/offer cancellation relevant к Jio | https://one.google.com/terms-of-service | official-terms | Last modified 2025-11-11; retrieved 2026-08-13 | “that third party or affiliate will charge your payment method and be responsible for managing any issues with your payment, including cancellations and refunds.” | Third-party seller responsibility for cancellation/refund handling. | Does not state Jio’s subscriber/SIM/plan-continuity conditions. |
| A6-7 | A6 ограничения eligibility/account/region/offer cancellation relevant к Jio | https://one.google.com/terms-of-service | official-terms | Last modified 2025-11-11; retrieved 2026-08-13 | “Some benefits may not be available in all countries and may be subject to other restrictions.” | Region/restriction caveat for Google One benefits. | Does not enumerate which Jio benefits survive outside India. |
| A6-GAP | A6 ограничения eligibility/account/region/offer cancellation relevant к Jio | Checked: https://blog.google/intl/en-in/company-news/partnering-with-reliance-to-bring-the-best-of-google-ai-to-more-people-across-india/ ; https://support.google.com/googleone/answer/15801606?hl=en ; https://one.google.com/terms-of-service | official-doc | Searched/opened 2026-08-13 | GAP — no opened Google primary source specifies Jio SIM continuity, ₹349 threshold, port-out revocation, resale, or gift-link transferability. | No Google-primary evidence for those Jio-specific conditions. | Queries checked: `site:support.google.com/googleone Jio 18 months cancellation`; `site:one.google.com Jio terms`; `site:blog.google Jio Google AI Pro eligibility cancellation`. Community answers and Jio pages were not counted. |
| A7-1 | A7 subscription loss/auth expiry observed or documented failure semantics | https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/packages/core/src/code_assist/oauth2.ts | official-source | `main` at `1ac3377395868295e128b96726d605a900b5946b`; retrieved 2026-08-13 | “const { token } = await client.getAccessToken();” | Source path obtains an access token from cached OAuth credentials before accepting them. | This source path is not a documented Jio subscription-loss probe. |
| A7-2 | A7 subscription loss/auth expiry observed or documented failure semantics | https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/packages/core/src/code_assist/oauth2.ts | official-source | `main` at `1ac3377395868295e128b96726d605a900b5946b`; retrieved 2026-08-13 | “This will check with the server to see if it hasn't been revoked.” | Source performs `getTokenInfo(token)` after obtaining the token. | Checks token revocation, not paid-plan entitlement. |
| A7-3 | A7 subscription loss/auth expiry observed or documented failure semantics | https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/packages/core/src/code_assist/oauth2.ts | official-source | `main` at `1ac3377395868295e128b96726d605a900b5946b`; retrieved 2026-08-13 | “Cached credentials are not valid:” | Invalid cached credentials are rejected by the cached-credential branch. | The log text does not distinguish expiry, revocation, or another validation error. |
| A7-4 | A7 subscription loss/auth expiry observed or documented failure semantics | https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/packages/core/src/code_assist/oauth2.ts | official-source | `main` at `1ac3377395868295e128b96726d605a900b5946b`; retrieved 2026-08-13 | “Manual authorization is required but the current session is non-interactive.” | Fatal non-interactive fallback when a new authorization is required and browser launch is suppressed. | It does not specify the process exit code or Jio-subscription-loss error payload. |
| A7-5 | A7 subscription loss/auth expiry observed or documented failure semantics | https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/docs/resources/faq.md | official-source | `main` at `1ac3377395868295e128b96726d605a900b5946b`; retrieved 2026-08-13 | “You can confirm you have higher limits by checking if you are still subscribed to Google AI Pro or Ultra” | Repository FAQ ties higher-limit entitlement to continuing subscription status. | It does not document the exact CLI error/state transition when the subscription disappears; consumer access is separately shut down. |
| A7-6 | A7 subscription loss/auth expiry observed or documented failure semantics | https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals?hl=en | official-doc | Last updated 2026-06-23; retrieved 2026-08-13 | “you can no longer use the Login with Google option” | Documented terminal consumer-auth state after shutdown. | This is a service deprecation semantic, not an observed Jio cancellation semantic. |
| A7-GAP | A7 subscription loss/auth expiry observed or documented failure semantics | Checked: https://support.google.com/googleone/answer/15801606?hl=en ; https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals?hl=en ; official OAuth source above | official-source | Searched/opened 2026-08-13 | GAP — no opened Google primary source gives the exact Gemini CLI response to loss of a Jio-provided subscription. | No exact Jio-loss error code, exit status, or automatic tier-transition evidence. | Queries checked: `site:geminicli.com authentication expired token error`; `site:github.com/google-gemini/gemini-cli refresh_token expired`; `site:support.google.com/googleone Jio subscription cancelled`. |
| A8-1 | A8 privacy/data-use различия login modes, если они влияют на runtime | https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/docs/resources/faq.md | official-source | `main` at `1ac3377395868295e128b96726d605a900b5946b`; retrieved 2026-08-13 | “Google does not use your data to improve Google's machine learning models if you purchase a paid plan.” | Published paid-plan data-use statement. | Consumer paid Google Login is disabled by A1-2; the statement remains in repository docs. |
| A8-2 | A8 privacy/data-use различия login modes, если они влияют на runtime | https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/docs/resources/faq.md | official-source | `main` at `1ac3377395868295e128b96726d605a900b5946b`; retrieved 2026-08-13 | “If you decide to remain on the free version of Gemini Code Assist, Gemini Code Assist for individuals, you can also opt out” | Published free-tier opt-out distinction from the paid-plan statement. | The linked individual privacy notice now redirects to the consumer deprecation page. |
| A8-3 | A8 privacy/data-use различия login modes, если они влияют на runtime | https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/docs/resources/tos-privacy.md | official-terms | `main` at `1ac3377395868295e128b96726d605a900b5946b`; retrieved 2026-08-13 | “Gemini Code Assist with Google AI Pro or Ultra subscription: Google Terms of Service, Google One Additional Terms of Service and Google Privacy Policy.” | Terms/privacy regime mapped to Pro/Ultra Google-account use. | Consumer Google Login is disabled; this mapping does not establish current runtime availability. |
| A8-4 | A8 privacy/data-use различия login modes, если они влияют на runtime | https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/docs/resources/tos-privacy.md | official-terms | `main` at `1ac3377395868295e128b96726d605a900b5946b`; retrieved 2026-08-13 | “Gemini Developer API Key” / “Gemini API - Unpaid Services” | API-key login maps to the Gemini Developer API rather than Gemini Code Assist service. | No API key is allowed by the task constraints; the row only records the terms/service distinction. |
| A8-5 | A8 privacy/data-use различия login modes, если они влияют на runtime | https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/docs/resources/tos-privacy.md | official-terms | `main` at `1ac3377395868295e128b96726d605a900b5946b`; retrieved 2026-08-13 | “Gemini Code Assist for individuals: Google Terms of Service and Gemini Code Assist for individuals Privacy Notice.” | Free Google-account mode’s published terms/privacy mapping. | The linked privacy notice redirects to deprecation; consumer Google Login no longer provides current Gemini CLI access. |

## Raw command evidence

All commands below were run read-only without login, API-key creation, promotion activation, or external-state mutation.

### Official repository revision

```text
$ git ls-remote https://github.com/google-gemini/gemini-cli.git refs/heads/main
1ac3377395868295e128b96726d605a900b5946b	refs/heads/main
```

### README: OAuth, free quota, models

```text
$ curl -fsSL 'https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/README.md' | nl -ba | rg 'Free tier.*requests/min|Gemini 3 models.*1M token|No API key management'
    19	- **🎯 Free tier**: 60 requests/min and 1,000 requests/day with personal Google
    21	- **🧠 Powerful Gemini 3 models**: Access to improved reasoning and 1M token
   159	- **Free tier**: 60 requests/min and 1,000 requests/day
   160	- **Gemini 3 models** with 1M token context window
   161	- **No API key management** - just sign in with your Google account
```

### Authentication document: cached headless credential

```text
$ curl -fsSL 'https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/docs/get-started/authentication.mdx' | nl -ba | sed -n '14,15p;49,50p;60,62p;445p;447,448p'
    14	For most users, we recommend starting Gemini CLI and logging in with your
    15	personal Google account.
    49	If you are a **Google AI Pro** or **Google AI Ultra** subscriber, use the Google
    50	account associated with your subscription.
    60	2. Select **Sign in with Google**. Gemini CLI opens a sign in prompt using your
   61	   web browser. Follow the on-screen instructions. Your credentials will be
   62	   cached locally for future sessions.
   445	## Running in headless mode <a id="headless"></a>
   447	[Headless mode](../cli/headless.md) will use your existing authentication
   448	method, if an existing authentication credential is cached.
```

### Repository quota and model-routing documents

```text
$ curl -fsSL 'https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/docs/resources/quota-and-pricing.md' | nl -ba | sed -n '19,21p;54,55p'
    19	| **Google account**    | Gemini Code Assist (Individual) | 1,000 requests                    |
    20	|                       | Google AI Pro                   | 1,500 requests                    |
    21	|                       | Google AI Ultra                 | 2,000 requests                    |
    54	- 1000 maximum model requests / user / day
    55	- Model requests will be made across the Gemini model family as determined by

$ curl -fsSL 'https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/docs/get-started/gemini-3.md' | nl -ba | sed -n '7,12p;74,77p'
     7	> Gemini 3.1 Pro Preview is rolling out. To determine whether you have
     8	> access to Gemini 3.1, use the `/model` command and select **Manual**. If you
     9	> have access, you will see `gemini-3.1-pro-preview`.
    10	>
    11	> If you have access to Gemini 3.1, it will be included in model routing when
    12	> you select **Auto (Gemini 3)**. You can also launch the Gemini 3.1 model
    74	- **Auto routing:** Auto routing first determines whether a prompt involves a
    75	  complex or simple operation. For simple prompts, it will automatically use
    76	  Gemini 2.5 Flash. For complex prompts, if Gemini 3 Pro is enabled, it will use
    77	  Gemini 3 Pro; otherwise, it will use Gemini 2.5 Pro.
```

### Current consumer deprecation

```text
$ curl -fsSL 'https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals?hl=en' | pandoc -f html -t plain --wrap=none | rg -n '^Starting June 18|^No, access'
72:Starting June 18, 2026, Gemini Code Assist IDE extensions stopped serving requests for the Gemini Code Assist for individuals, Google AI Pro, and Google AI Ultra tiers. This also applies to usage of Gemini CLI. As part of the deprecation, you can no longer use the Login with Google option to access the IDE extensions or Gemini CLI. For more information, see the Google I/O announcement.
80:No, access to Gemini Code Assist IDE extensions and Gemini CLI using Gemini Code Assist Standard or Enterprise subscriptions remain unchanged.
```

### Current Gemini CLI/agent-mode quota table

```text
$ curl -fsSL 'https://docs.cloud.google.com/gemini/docs/quotas?hl=en' | pandoc -f html -t plain --wrap=none | rg -n '^Quotas for agent|^Quotas for requests|Maximum requests per user per day|Enterprise +2000'
207:Quotas for agent mode and Gemini CLI
209:Quotas for requests from Gemini Code Assist agent mode and Gemini CLI are combined. When in agent mode or when using the Gemini CLI, one prompt might result in multiple model requests. Requests are limited per user per minute and are subject to the availability of the service in times of high demand. These daily request limits are aggregated across all interactions with any model version or family (for example, Pro, Flash) used with the Gemini CLI or agent mode. Once the maximum number of requests per day is reached, no further requests can be made through these interfaces to any model until the quota resets.
213:  Maximum requests per user per day   Standard                     1500
214:                                      Enterprise                   2000
```

### Google Jio announcement and zero CLI/Code Assist matches

```text
$ curl -fsSL 'https://blog.google/intl/en-in/company-news/partnering-with-reliance-to-bring-the-best-of-google-ai-to-more-people-across-india/' | pandoc -f html -t plain --wrap=none | rg -n 'Jio Unlimited 5G|18 to 25|MyJio app|2 TB'
112:Today we announced a strategic partnership with Reliance Intelligence to offer Google’s AI Pro plan, and with it the latest version of Google Gemini, to Jio Unlimited 5G plan users at no extra cost for 18 months. This offer will begin rolling out to users between 18 to 25 years of age, and will soon extend to include every eligible Jio user nationwide.
114:Eligible Jio customers will gain higher access to our most capable Gemini 2.5 Pro model in the Gemini app, higher limits to generate stunning images and videos with our state-of-the-art Nano Banana and Veo 3.1 models, expanded access to NotebookLM for study and research, 2 TB of cloud storage across Google Photos, Gmail, Drive and for backing up WhatsApp (on Android) and more – a combined value of approximately ₹35,100.
116:Eligible Jio users can activate this offer via the MyJio app.

$ curl -fsSL 'https://blog.google/company-news/inside-google/around-the-globe/google-asia/reliance-jio-india-partnership/' | pandoc -f html -t plain --wrap=none | rg -n 'Eligible users in India|18 months|2 TB'
253:Through a new strategic partnership with Reliance Intelligence, we're bringing together our most capable AI models and powerful tools, giving millions of their users access to the Google AI Pro plan at no extra cost for 18 months.
255:Subscribers will be able to use Gemini 2.5 Pro, get higher limits for creating images and videos and use NotebookLM for research. The offer also includes 2 TB of cloud storage across Google Photos, Gmail and Drive. Eligible users in India can activate the offer through the MyJio app.

$ curl -fsSL 'https://blog.google/intl/en-in/company-news/partnering-with-reliance-to-bring-the-best-of-google-ai-to-more-people-across-india/' | pandoc -f html -t plain --wrap=none | rg -io 'Gemini CLI|Code Assist' | sort | uniq -c; test ${PIPESTATUS[2]} -eq 1 && echo 'matches=0' || true
matches=0
```

### Google One third-party activation and cancellation

```text
$ curl -fsSL 'https://support.google.com/googleone/answer/15801606?hl=en' | pandoc -f html -t plain --wrap=none | rg -n 'personal Google Account|membership status with the provider'
64:-   To activate your Google One subscription, you need a personal Google Account. Learn how to create a Google Account.
71:When you activate your account, you consent to Google One’s Terms of Service. You also consent to Google sharing your membership status with the provider so you can start, stop, or change your Google One plan through them.

$ curl -fsSL 'https://support.google.com/googleone/answer/15801606?hl=en' | pandoc -f html -t plain --wrap=none | sed -n '75,90p;112,122p'
Activation link expired

-   The subscription link has expired if it has passed its validity period.
-   To get a new link, click or tap Return to [Partner].

Subscription already in use

-   The subscription link has already been used to activate the subscription of an eligible Google Account.
-   To explore Google One for benefits and other offers, click or tap Explore Google One.

What happens if my Google Account:

Already has a Google One subscription through another provider?

To start your new plan, cancel the old one.

-   Google One can be canceled either in the Google One app or through your provider. To cancel in the Google One app, go to Settings.
    -   To cancel Google One plans from Metro by T-Mobile, use the Google One app.
    -   To cancel Google One plans from other providers, use their website or contact their customer service.
-   Your current plan may be canceled immediately or continue until the end of the billing cycle based on your provider’s policies.
    -   Any refunds for plan cancellations are handled by your provider.

After the current plan is canceled, to start the new plan, use the activation link. Learn how to cancel your Google One membership.
```

```text
$ curl -fsSL 'https://one.google.com/terms-of-service' | pandoc -f html -t plain --wrap=none | rg -n 'third party or affiliate|responsible for managing|cancel or suspend|Some benefits may not be available'
17:Google One offers subscription plans with paid storage shared across Gmail, Google Photos, and Google Drive, including subscription plans with additional benefits provided to you by Google or through third parties. Google One also offers subscription plans and AI credits for paid access to certain AI features built by Google. Your use of additional Google or third-party benefits is governed by the terms of service applicable to such benefits. Some benefits may not be available in all countries and may be subject to other restrictions. Please visit the Google One Help Center for more information.
19:The Google One service is provided to you by the Google entity set out in the Google Terms of Service. When you purchase a Google One subscription or AI credits, you enter into a separate contract with the seller, which may be a Google entity (see Section 2) or a third party. If you have a Google One subscription through a third party or affiliate, then your subscription may be subject to additional terms from that third party or affiliate.
44:When you purchase a Google One subscription or AI credits through a third party or affiliate, that third party or affiliate will charge your payment method and be responsible for managing any issues with your payment, including cancellations and refunds.
46:If the seller is unable to charge you for the Google One subscription, you may not be able to access Google One until you update your form of payment with the seller. If you fail to update your form of payment within a reasonable amount of time following that notice, we may cancel or suspend your access to Google One.
```

### OAuth invalidation and non-interactive failure path

```text
$ curl -fsSL 'https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/packages/core/src/code_assist/oauth2.ts' | nl -ba | sed -n '195,196p;199p;201,202p;222p;224p;260,263p'
   195	      const client = createBaseOAuth2Client();
   196	      client.setCredentials(credentials as Credentials);
   199	        const { token } = await client.getAccessToken();
   201	          // This will check with the server to see if it hasn't been revoked.
   202	          await client.getTokenInfo(token);
   222	      } catch (error) {
   224	          'Cached credentials are not valid:',
   260	  if (config.isBrowserLaunchSuppressed()) {
   261	    if (!config.isInteractive()) {
   262	      throw new FatalAuthenticationError(
   263	        'Manual authorization is required but the current session is non-interactive. ' +
```

### Subscription entitlement and privacy text still present in repository docs

```text
$ curl -fsSL 'https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/docs/resources/faq.md' | nl -ba | sed -n '153,157p;176,180p'
   153	If you're subscribed to Google AI Pro or Ultra, you automatically have higher
   154	limits to Gemini Code Assist and Gemini CLI. These are shared across Gemini CLI
   155	and agent mode in the IDE. You can confirm you have higher limits by checking if
   156	you are still subscribed to Google AI Pro or Ultra in your
   157	[subscription settings](https://one.google.com).
   176	Google does not use your data to improve Google's machine learning models if you
   177	purchase a paid plan. Note: If you decide to remain on the free version of
   178	Gemini Code Assist, Gemini Code Assist for individuals, you can also opt out of
   179	using your data to improve Google's machine learning models. See the
   180	[Gemini Code Assist for individuals privacy notice](https://developers.google.com/gemini-code-assist/resources/privacy-notice-gemini-code-assist-individuals)
```

```text
$ curl -fsSL 'https://raw.githubusercontent.com/google-gemini/gemini-cli/1ac3377395868295e128b96726d605a900b5946b/docs/resources/tos-privacy.md' | nl -ba | sed -n '44p;46,47p;57,63p'
    44	| Authentication Method    | Service(s)                   | Terms of Service                                                                                        | Privacy Notice                                                                                |
    46	| Google Account           | Gemini Code Assist services  | [Terms of Service](https://developers.google.com/gemini-code-assist/resources/privacy-notices)          | [Privacy Notices](https://developers.google.com/gemini-code-assist/resources/privacy-notices) |
    47	| Gemini Developer API Key | Gemini API - Unpaid Services | [Gemini API Terms of Service - Unpaid Services](https://ai.google.dev/gemini-api/terms#unpaid-services) | [Google Privacy Policy](https://policies.google.com/privacy)                                  |
    57	- Gemini Code Assist for individuals:
    58	  [Google Terms of Service](https://policies.google.com/terms) and
    59	  [Gemini Code Assist for individuals Privacy Notice](https://developers.google.com/gemini-code-assist/resources/privacy-notice-gemini-code-assist-individuals).
    60	- Gemini Code Assist with Google AI Pro or Ultra subscription:
    61	  [Google Terms of Service](https://policies.google.com/terms),
    62	  [Google One Additional Terms of Service](https://one.google.com/terms-of-service)
    63	  and [Google Privacy Policy\*](https://policies.google.com/privacy).
```
