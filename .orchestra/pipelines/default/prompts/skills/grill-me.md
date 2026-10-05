---
name: grill-me
description: "Interview the user relentlessly about a plan or design until reaching shared understanding and resolving each branch of the decision tree. Use when the user wants to stress-test a plan, get grilled on a design, or mentions \"grill me\"."
roles: [all]
integrations: [web-search]
---

# Grill Me — stress-test a plan, business, or product

## Purpose

Relentlessly stress-test a plan, business model, or product through evidence-based question
frameworks. Find contradictions, blind spots, and untested assumptions. Record the answers.

## When to invoke

- "grill me", "stress-test", "criticize this", "find the weak spots"
- "fundamental questions", "contradictions", "stress test"
- "devil's advocate", "take it apart", "poke holes"
- The user shares a plan and wants it challenged

## Methodology (five question frameworks)

### 1. Pre-mortem (Gary Klein, HBR 2007)

Imagine the project has ALREADY failed: "A year has passed; the project is dead. Why?" Shifting
from "what could go wrong" to "what went wrong" improves risk identification by 30% (Wharton,
"Back to the Future", 1989). Future tense → past tense is prospective hindsight.

### 2. Socratic questioning (six types)

- **Clarification:** "What do you mean by X?"
- **Probing assumptions:** "Why do you believe X is true? What is it based on?"
- **Probing evidence:** "What data supports this? How do you know?"
- **Exploring alternatives:** "What if the opposite is true? What else could work?"
- **Implications:** "If X is true, what follows?"
- **Meta-questions:** "Why does this question matter at all?"

### 3. Assumption mapping (Bland & Osterwalder, 2019)

Use a 2×2 matrix: importance × uncertainty. CB Insights reports that 42% of startups die from
"no market need" — untested demand assumptions.

- Desirability: "Do customers WANT this?" (most often fatal)
- Feasibility: "CAN we build this?" (less often fatal)
- Viability: "WILL it pay off?" (often ignored)

### 4. Five Whys (Toyota, Taiichi Ohno)

For every weak answer, dig deeper. Ask "Why?" across five levels. The goal is the root cause,
not the symptom.

### 5. Red team (US military → business)

Adopt the role of a competitor/critic: "If I wanted to destroy this business, how would I do it?"
This is a formal devil's advocate.

## Process flow

### Phase 1: Silent analysis

Read documents relevant to the plan. Build a map:

- What claims are made?
- What evidence exists?
- What is accepted without verification?
- Where do documents contradict one another?
- Which obvious questions were NOT asked?

### Phase 2: Pre-mortem

Start with one question:

> "Imagine: a year has passed and [project] failed. Customers left and money ran out. What happened? Name the three most likely causes."

Record the answer. Then continue.

### Phase 3: Structured grill (10 questions as one batch)

Choose the 5–7 most relevant categories:

- 🏗️ **Foundation** — why does this exist, who needs it, what is the evidence?
- 💰 **Unit economics** — CAC, LTV, margin, break-even point
- ⚔️ **Competitors/moat** — who already does this, how are you better, what if X appears tomorrow?
- 📈 **Scale** — what if usage grows 10×, what breaks first, where is the single point of failure?
- ⚠️ **Risks** — vendor, legal, and technical dependencies
- 🎯 **Sales** — who buys, how do you find them, sales cycle, conversion?
- 📋 **Operations** — who does the work, SLA, what if you become ill?
- 🔄 **Contradictions** — "Document A says X; document B says Y — which is true?"

**Question rules:**

- Every question cites a CONCRETE fact/document, not a generic "have you considered…?"
- For a contradiction, quote BOTH sides.
- Move from fundamentals to details.
- Match the user's style: direct, without corporate language.
- Give each question its own recommended answer when you have an opinion.

### Phase 4: Deep dive (Five Whys)

For weak answers ("no idea", "later", "somehow"), ask Five Whys:

> "Why is there no SLA?" → "Because I work alone" → "Why alone?" → "Because there is no money for an employee" → "Why?" → "Because there is one customer" → ROOT CAUSE: get a second customer before hiring.

### Phase 5: Red team

End with one question:

> "I am your competitor. I have a $5M budget and a team of ten. How do I kill your business in six months?"

### Phase 6: Record

Record everything in a document:

```markdown
## Grill [topic] — [date]

### Pre-Mortem: three failure causes
1. ...

### Questions and answers
**🏗️ Q: [question]**
A: [answer]

### Assumption Map
| Assumption | Importance | Tested? | How to test |
|---|---|---|---|

### Unresolved questions
- [ ] ...

### Red Team: how to kill the business
...
```

### Phase 7: Next batch

"Another 10 questions, or go deeper into [topic]?" Each next batch goes deeper into weak spots.
Stop when the user says to stop.

## Error handling

- Vague answer ("no idea", "later") → record it + ⚠️ + Five Whys
- Defensive reaction → normal; do not soften. "Better now than a customer in a month."
- No documents → ask verbally and grill the answers
