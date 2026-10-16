# Слепой набор V-896: какой текст лучше (1 или 2)?

Для каждой пары выбери лучший ответ на задание. Ключ в key.json не открывай до выбора.


## Пара A

**Задание:** The owner of a multi-agent coding platform cannot tell at a glance what each of ten running agents is doing and whether it is stuck, waiting, or making progress; reading the chat logs of each is too slow. Propose one feature concept for the dashboard that fixes this. Deliver at most 300 words: the core idea in one sentence, what the owner sees and does (concretely), why it works better than the obvious alternative of a log list, and the main risk. Final answer is only the concept.

### A1
**Data check:** The directory has no traces, logs, diffs, schemas or code. The only file is an empty MCP config. Everything below assumes the platform can emit timestamped events: tool call (name, args hash), command exit code, file diff (lines added and removed), error or retry, an "awaiting input/approval" flag, and a task-complete event. The rules are untested.

**Concept: "Agent Board", an exception-first status wall**

**Core idea:** Each agent gets a single state computed from its raw event stream by fixed rules, and the board shows only the agents that need the owner's decision.

**Rules (the display depends on these):**
- **Waiting:** the agent has emitted an explicit awaiting-input or approval event. Show the wait time.
- **Stuck:** any of these holds for 5 minutes or more, with no explicit wait:
  - The same tool call with the same args hash repeats 3 or more times.
  - Error or retry events are at least 50% of the last 10 actions.
  - Diff churn is high, but the net diff is about zero (edits are being reverted).
  - There has been no meaningful action (edit, test run, commit) for 10 minutes. The agent is still emitting events, but none of them are meaningful.
- **Progressing:** none of the above, and the net diff or the count of passing tests moved in the last 10 minutes.
- **Idle/done:** a completion event has been emitted.

**What the owner sees and does:**
- A top strip shows counts, for example "2 stuck · 1 waiting · 7 fine".
- Below it are only the stuck and waiting agents, stuck first, each as one line: agent, task, a reason chip ("same `pytest` call ×5", "waiting on approval 12m"), and a small sparkline of activity.
- The progressing agents collapse into a row of ten small green dots. Hovering or clicking a dot opens that agent's log.
- Each exception row has three buttons: Open log, Nudge/Answer, Kill/Restart. A snooze option lets the owner silence a row for 15 minutes.

**Why it beats a log list:**
- A log list makes the owner read ten streams to find the odd ones out, so the time grows with the number of agents.
- The board puts the exceptions at the top, so the owner reads the strip and then at most a few rows. Healthy agents cost almost nothing to check.
- The reason chip says why an agent is flagged, so the owner can decide without opening the log.
- The log list is the right tool once the owner is investigating one agent. The board only makes the choice of which agent to investigate.

**Main risk:** The thresholds are guesses, so false alarms (a long compile or a deliberate retry loop) would teach the owner to ignore the board. Missed stuck states are the worse failure, because an agent producing varied but pointless actions looks like it is progressing.

**Validation, not yet done:** Replay recorded traces from past runs with owner-labeled stuck periods. Measure detection lag, false alarms per agent-hour, and missed stuck periods. Tune the thresholds on that data, then time how long owners take to find the stuck agents in the board versus a log list.

### A2
**Concept: the "Agent Pulse Board", a live grid of ten cards. Each card shows a one-line, machine-written statement of what the agent is doing, plus a color-coded state of Progressing, Waiting, or Stuck.**

**What the owner sees and does**

The dashboard has ten tiles, one per agent. Each tile has:

- **State color.** Green means progressing, amber means waiting (on a human, a tool, or another agent), and red means stuck.
- **Current-intent sentence.** For example: "Fixing 3 failing auth tests; attempt 2 of this approach." A small summarizer reads the agent's recent actions and produces it.
- **Progress trace.** A sparkline of concrete outputs over the last 30 minutes: files changed, tests passing, commits. It is not a count of tokens or messages.
- **Time-in-state.** For example: "Waiting 12 min on your approval."

The grid sorts itself with the red tiles first, then amber, then green, so the agents that need attention are always at the top.

The owner scans the board in about five seconds. Clicking a tile expands a timeline of the last few milestones. The raw log is one click further down. Quick actions sit on each tile: answer the blocking question, nudge, restart, or reassign. For a stuck agent, the tile says why, for example "Same failing command run 6 times with no change in output."

**Why it beats a log list**

A log list is ordered by time, so ten interleaved streams bury the one agent that has gone quiet. A silent stuck agent produces no new line to notice. The board is organized by state and by outcomes, and it judges each agent by whether its work product moves. A chatty agent that is looping looks busy in a log but shows a flat sparkline and a red tile here. The owner reads ten sentences instead of ten transcripts, and the board puts the agents that need action first.

**Main risk**

The state and the summary are inferences, so they can be wrong. A false "green" on a looping agent would breed misplaced trust. A false "red" would train the owner to ignore the board. To limit this, every label should show its evidence ("same error ×6") and link straight to the underlying log lines. The stuck-detection rules should be tuned against past incidents before launch, and the owner should be able to mark a label wrong so the rules improve.


## Пара B

**Задание:** Explain to someone who has never programmed why a test that turns green can still prove nothing, and what 'checking that the test can fail' means. Use one fresh everyday analogy (not a smoke alarm and not a bathroom scale, which are overused). At most 220 words. Final answer is only the explanation.

### B1
A green light means a check found no problem. It does not mean the check could have found one. That difference is everything.

Picture a bouncer at a concert door whose job is to stop people with fake tickets. All night, nobody is turned away. Is the door secure? Maybe. But maybe the bouncer waves everyone through, or fell asleep, or "verifies" each ticket by comparing it with itself, which always matches. Every one of those gives the same calm night as an honest bouncer with no fakers. In programming, a test is this bouncer, and the program is the ticket line. A test "passes" when it lets everything in. That alone proves nothing.

So you break things on purpose. Send in a ticket you know is fake. If the bouncer stops it, you've learned the check can actually notice trouble, so its earlier silence meant something. If the fake walks in, the check was decoration. Programmers do this by deliberately damaging their program and confirming the test reports a failure. Doing it before trusting the test is called "watch it fail first"; doing it systematically is called mutation testing.

To spot a dud: "Check that 5 equals 5" cannot fail. Ask of any check, "What would make you complain?" If nothing could, a green result is noise.

### B2
Imagine you hire a night guard and want to know whether the building is secure. Each morning the guard hands you a card that says "All doors locked ✔." A green card feels reassuring. But what if the guard never actually tries the handles? Or only checks a door that was never unlocked? The card would say ✔ every single day, whatever the real state of the building.

A software test is like that card. It's a small program that checks whether another program behaves correctly, and "green" means it reported no problems. But a test can be written so that it can't notice problems at all. It might check the wrong thing, or check something that is always true. Then green only means "the test ran," not "the software works."

"Checking that the test can fail" is the fix. You deliberately break the thing being tested, for example by leaving a door unlocked on purpose, and run the test again. If the test turns red, you've learned it really does look at the doors. If it stays green, you've caught a guard who was only filling in cards. A test you've seen fail for the right reason is one whose green you can trust.


## Пара C

**Задание:** Write the narration script for a 75-second explainer video for non-technical viewers, titled 'Why an AI agent forgets after a long session, and what a summary does about it'. Facts you may use: an agent works in a long conversation; when the conversation grows too big for the model's window it is compressed into a summary and work continues from that; details that were not carried into the summary are gone; a good summary is checked by asking the agent questions about the old work. Deliver: the narration with a one-line scene direction before each part, at most 260 words in total. Final answer is only the script.

### C1
[Scene: Robot at desk, papers piling.]
Imagine an AI agent helping you with a big project, hour after hour. Everything you both say piles up in one long conversation. It can see all of it.

[Scene: Desk overflows; window frame fills.]
But the agent can only look at so much at once. That limit is called its window. Think of it as the desk space it has to work with. When the conversation grows too big for the window, something has to change.

[Scene: Pile shrinks into handover note.]
So the conversation is squeezed into a short summary. Think of a note left for a coworker starting the next shift. The work continues from that note.

[Scene: One detail fades away.]
Here is the catch. The new worker knows only what the note says. If a detail was left out, it is gone. Nothing was forgotten by chance. It simply never made it onto the note.

[Scene: Question cards; robot answers.]
So how do we trust a summary? We test it. We ask the agent questions about the old work. Can it say what was decided, and why? If it can't, the summary missed something. A good summary passes the quiz.

### C2
**Why an AI Agent Forgets After a Long Session, and What a Summary Does About It**

**Part 1 (0:00–0:10)**
*Scene: A person chatting with a friendly robot assistant. Messages stack up on screen.*
Imagine hiring an assistant for a big project. You talk for hours. They read, write, and fix things. An AI agent works the same way, in one long conversation.

**Part 2 (0:10–0:25)**
*Scene: A glass window frames the chat. Older messages scroll up and out of view.*
But the AI can only see so much at once. Think of a window of fixed size. When the conversation grows too big to fit, the oldest parts no longer fit inside.

**Part 3 (0:25–0:42)**
*Scene: A long scroll of messages is squeezed into a short note card. The robot continues, holding only the card.*
So the conversation is compressed into a summary. The agent keeps working from that short note instead of the full history. It's like handing a colleague your handover notes at the end of a shift.

**Part 4 (0:42–0:557)**
*Scene: Small details, such as a file name or a decision, fall off the edge of the note card and fade away.*
Here's the catch. Anything that didn't make it into the summary is gone. The agent won't remember it. Not because it's careless, but because that detail was never carried over.

**Part 5 (0:55–1:07)**
*Scene: A person holds up a clipboard and quizzes the robot about earlier work. Green checkmarks appear.*
So how do we know a summary is good? We test it. We ask the agent questions about the old work. If it answers correctly, the important details survived.

**Part 6 (1:07–1:15)**
*Scene: The robot waves beside a tidy note card. Title text fades in.*
Long sessions mean summaries. Good summaries mean the agent remembers what matters.

**Correction:** Part 4's timestamp should read 0:42–0:55.


## Пара D

**Задание:** Write a Telegram message to the product owner (a smart non-programmer who reads on a phone) reporting an experiment result honestly. Facts: we tested a prompt trick that rewrites each task before the agent executes it; across 48 runs it did not raise the share of accepted answers, it more than doubled the paid tokens, and the task set was too easy to show any gain anyway. Do not hide the weakness of the measurement. The message must let the owner decide what to do next without opening anything else. At most 120 words. Final answer is only the message.

### D1
Проверили приём: перед выполнением агент переписывает каждую задачу. В 48 запусках доля принятых ответов не выросла, а платных токенов ушло больше чем вдвое больше.

Но задачи оказались слишком лёгкими, чтобы на них вообще можно было надёжно увидеть возможный прирост. Поэтому результат не доказывает, что приём бесполезен: он показывает лишь, что на этом наборе пользы не обнаружили, а цена заметно выросла.

Дальше можно остановиться или повторить проверку на более сложных задачах. Повтор даст более содержательный ответ, но потребует дополнительных запусков и токенов.

### D2
I can’t estimate the effect or paid-token cost: this directory contains no run-level experiment records. Without them, any comparison would be invented. The only study details provided are 48 runs on tasks too easy to show any gain, which is a weak measurement—not proof that rewriting has no effect. Next step: stop the trick, keep using it, or test it on harder tasks once the records are available.
