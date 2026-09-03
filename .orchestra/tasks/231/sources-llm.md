### 1

- id: 1
- name: Anthropic multi-agent Research system
- origin: Anthropic engineering blog, 2025, Anthropic
- topology: star
- shared_state: LeadResearcher context window and its Memory store hold the plan and returned findings; each subagent has a separate context window.
- wake_rule: The LeadResearcher proceeds when the current synchronously executed set of subagents has completed, then synthesizes their findings.
- wakeups_per_N: 1 (derived)
- coordinator_rereads_context: yes, because returned findings enter the LeadResearcher context for synthesis and the next research decision.
- results_return_via: return value
- parent_blocked_while_child_runs: yes
- who_decides_next_task: coordinator
- failure_mode_named_in_source: One slow subagent can block the whole synchronous set and therefore the entire system.
- wins_on_task_class: Breadth-first research with multiple independent directions, information beyond one context window, and many complex tools; +90.2% on Anthropic's internal research eval.
- coordination_cost_number: "multi-agent systems use about 15× more tokens than chats"
- source_url: https://www.anthropic.com/engineering/multi-agent-research-system
- tier: 2 primary
- quote: "lead agents execute subagents synchronously, waiting for each set of subagents to complete before proceeding. ... entire system can be blocked while waiting for a single subagent"

### 2

- id: 2
- name: Claude Code subagents
- origin: Claude Code documentation, 2026, Anthropic
- topology: star
- shared_state: The parent conversation receives the final completion notification; each subagent keeps a separate transcript at `~/.claude/projects/{project}/{sessionId}/subagents/agent-{agentId}.jsonl`.
- wake_rule: A background subagent completion creates a notification delivered to Claude in a later parent turn.
- wakeups_per_N: N (derived)
- coordinator_rereads_context: yes, because every completion notification is delivered in a later turn of the parent conversation.
- results_return_via: message
- parent_blocked_while_child_runs: no
- who_decides_next_task: coordinator
- failure_mode_named_in_source: A rate-limit, overload, or server error can cut a subagent off; the parent receives partial output or a failed completion.
- wins_on_task_class: Focused side tasks whose search results, logs, or file contents should not flood the main conversation.
- coordination_cost_number: UNKNOWN
- source_url: https://code.claude.com/docs/en/sub-agents
- tier: 2 primary
- quote: "A background subagent’s results reach Claude as a completion notification in a later turn. ... partial output ... subagent was cut off and didn’t finish its task."

### 3

- id: 3
- name: Claude Code Agent Teams
- origin: Claude Code Agent Teams research preview, 2026, Anthropic
- topology: mesh
- shared_state: The shared task list is stored under `~/.claude/tasks/{team-name}/`; each agent mailbox is `~/.claude/teams/{team-name}/inboxes/{agent-name}.json`.
- wake_rule: The lead receives teammate messages automatically and receives an automatic notification when each teammate finishes and becomes idle.
- wakeups_per_N: N + M, where M is the number of teammate messages (derived)
- coordinator_rereads_context: yes, because teammate messages and idle notifications are delivered into the lead session automatically.
- results_return_via: message
- parent_blocked_while_child_runs: no
- who_decides_next_task: other
- failure_mode_named_in_source: Before v2.1.207, one malformed mailbox entry repeated an error every second and blocked that mailbox's delivery.
- wins_on_task_class: Parallel research and review, independent modules, competing debugging hypotheses, and cross-layer work.
- coordination_cost_number: UNKNOWN
- source_url: https://code.claude.com/docs/en/agent-teams
- tier: 2 primary
- quote: "when a teammate finishes and stops, it automatically notifies the lead. ... a single malformed mailbox entry ... blocked delivery for that mailbox"

### 4

- id: 4
- name: OpenAI Agents SDK handoffs
- origin: OpenAI Agents SDK, 2025, OpenAI
- topology: pipeline
- shared_state: Application state lives in `RunContextWrapper.context`; by default the receiving agent also gets the complete prior conversation history within the same run.
- wake_rule: The current agent's LLM calls a handoff tool such as `transfer_to_refund_agent`, which transfers control to the registered destination agent.
- wakeups_per_N: NA (no N-way parallel round)
- coordinator_rereads_context: yes, because the receiving agent sees the entire previous conversation history unless an input filter changes it.
- results_return_via: return value
- parent_blocked_while_child_runs: yes
- who_decides_next_task: worker itself
- failure_mode_named_in_source: Input guardrails cover only the first agent in a handoff chain, leaving later handoff agents outside that input-guardrail boundary.
- wins_on_task_class: Workflows with distinct specialists, such as separate order-status, refund, and FAQ agents.
- coordination_cost_number: UNKNOWN
- source_url: https://openai.github.io/openai-agents-python/handoffs/
- tier: 2 primary
- quote: "Handoffs are represented as tools to the LLM. ... Input guardrails still apply only to the first agent in the chain."

### 5

- id: 5
- name: OpenAI Swarm
- origin: Swarm experimental educational framework, 2024, OpenAI Solutions team
- topology: mesh
- shared_state: `messages`, the last active `Agent`, and `context_variables` live in the client-side `Response`; Swarm stores no state between calls.
- wake_rule: During `client.run()`, a function result containing another `Agent` transfers execution to that agent and the loop requests the next completion.
- wakeups_per_N: NA (no N-way parallel round)
- coordinator_rereads_context: yes, because agent instructions change on handoff but the chat history remains in the next completion input.
- results_return_via: return value
- parent_blocked_while_child_runs: yes
- who_decides_next_task: worker itself
- failure_mode_named_in_source: If one agent calls several handoff functions in the same turn, only the last handoff is used.
- wins_on_task_class: A large number of independent capabilities and instructions that are difficult to encode in one prompt.
- coordination_cost_number: UNKNOWN
- source_url: https://github.com/openai/swarm
- tier: 2 primary
- quote: "If a function returns an Agent, execution will be transferred to that Agent. ... If an Agent calls multiple functions ... only the last handoff function will be used."

### 6

- id: 6
- name: LangGraph supervisor
- origin: `langgraph-supervisor-py` library, 2025, LangChain
- topology: tree
- shared_state: Messages live in the LangGraph state; optional checkpointer and store instances persist short- and long-term state.
- wake_rule: The central supervisor is invoked initially and again after each worker result enters the graph history, deciding which specialist to invoke next.
- wakeups_per_N: N + 1 (derived)
- coordinator_rereads_context: yes, because supervisor routing uses the current context and message history after worker responses.
- results_return_via: message
- parent_blocked_while_child_runs: yes
- who_decides_next_task: coordinator
- failure_mode_named_in_source: A subagent can perform tool calls or reasoning but omit the results from its final message, leaving the supervisor without them.
- wins_on_task_class: Hierarchical systems in which a central supervisor routes work among specialized agents.
- coordination_cost_number: UNKNOWN
- source_url: https://github.com/langchain-ai/langgraph-supervisor-py ; https://docs.langchain.com/oss/python/langchain/multi-agent/subagents
- tier: 2 primary
- quote: "By default, subagent calls are synchronous: the main agent waits for each subagent to complete before continuing. ... A common failure mode is ... doesn’t include results."

### 7

- id: 7
- name: LangGraph Send API orchestrator-worker
- origin: LangGraph workflow documentation, 2024, LangChain
- topology: star
- shared_state: Worker-local states write outputs into a reducer-annotated key in the parent `StateGraph` state.
- wake_rule: The downstream synthesizer node becomes runnable after all parallel worker nodes have written their outputs to the shared state key.
- wakeups_per_N: 1 (derived)
- coordinator_rereads_context: no, because a distinct synthesizer reads the accumulated shared key once after the parallel barrier.
- results_return_via: shared store
- parent_blocked_while_child_runs: yes
- who_decides_next_task: static graph
- failure_mode_named_in_source: Parallel nodes that overwrite the same state key without a compatible reducer raise `InvalidUpdateError`.
- wins_on_task_class: Orchestrator-worker workflows whose subtasks cannot be predefined, including code-writing and multi-file content updates.
- coordination_cost_number: UNKNOWN
- source_url: https://docs.langchain.com/oss/python/langgraph/workflows-agents ; https://docs.langchain.com/oss/python/langgraph/use-graph-api
- tier: 2 primary
- quote: "all worker outputs are written to a shared state key ... If multiple nodes attempt to overwrite the same key ... an InvalidUpdateError will be raised."

### 8

- id: 8
- name: langgraph-swarm
- origin: `langgraph-swarm-py` library, 2025, LangChain
- topology: mesh
- shared_state: A parent `StateGraph` carries a shared `messages` list and `active_agent`; a checkpointer and store optionally persist them across interactions.
- wake_rule: A handoff tool returns `Command(goto=agent_name)` and updates `active_agent`, making the chosen agent the next graph node.
- wakeups_per_N: NA (no N-way parallel round)
- coordinator_rereads_context: NA, because there is no central coordinator; agents hand control directly to one another.
- results_return_via: shared store
- parent_blocked_while_child_runs: yes
- who_decides_next_task: worker itself
- failure_mode_named_in_source: Without a short-term-memory checkpointer, the swarm forgets the last active agent and loses conversation history across interactions.
- wins_on_task_class: Multi-turn conversations that dynamically hand off among specialized agents.
- coordination_cost_number: UNKNOWN
- source_url: https://github.com/langchain-ai/langgraph-swarm-py
- tier: 2 primary
- quote: "agents dynamically hand off control to one another ... Without it, the swarm would \"forget\" which agent was last active and lose the conversation history."

### 9

- id: 9
- name: AutoGen GroupChat / SelectorGroupChat
- origin: AutoGen group-chat design pattern, 2023, Microsoft Research
- topology: bus
- shared_state: Agents publish to a common runtime topic; the manager and participants keep Python `_chat_history` lists of received messages.
- wake_rule: Every `GroupChatMessage` received on the common topic activates the Group Chat Manager to select and request the next speaker.
- wakeups_per_N: N (derived)
- coordinator_rereads_context: yes, because the manager formats its accumulated `_chat_history` into the selector prompt on every turn.
- results_return_via: message
- parent_blocked_while_child_runs: yes
- who_decides_next_task: coordinator
- failure_mode_named_in_source: The group chat can enter an infinite loop, so the documented example caps it at 25 messages.
- wins_on_task_class: Dynamic decomposition of a complex task among specialized agents with well-defined roles.
- coordination_cost_number: UNKNOWN
- source_url: https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/design-patterns/group-chat.html ; https://microsoft.github.io/autogen/dev/user-guide/agentchat-user-guide/selector-group-chat.html
- tier: 2 primary
- quote: "selects the next agent to speak upon receiving a message. ... limit the conversation to 25 messages to avoid infinite loop."

### 10

- id: 10
- name: AutoGen Magentic-One
- origin: Magentic-One technical system, 2024, Microsoft Research / arXiv 2411.04468
- topology: star
- shared_state: The Orchestrator maintains a Task Ledger for facts and plan plus a Progress Ledger for per-step progress and completion checks.
- wake_rule: After each assigned agent completes its subtask, the Orchestrator updates the Progress Ledger, checks completion or stall, and assigns the next subtask.
- wakeups_per_N: N (derived)
- coordinator_rereads_context: yes, because every return triggers an Orchestrator update and self-reflection over the Progress Ledger.
- results_return_via: message
- parent_blocked_while_child_runs: yes
- who_decides_next_task: coordinator
- failure_mode_named_in_source: Magentic-One may be susceptible to prompt-injection attacks from webpages.
- wins_on_task_class: Open-ended web- and file-based tasks across domains, including GAIA benchmark tasks.
- coordination_cost_number: UNKNOWN
- source_url: https://microsoft.github.io/autogen/dev/user-guide/agentchat-user-guide/magentic-one.html
- tier: 2 primary
- quote: "After the assigned agent completes its subtask, the Orchestrator updates the Progress Ledger. ... Magentic-One may be susceptible to prompt injection attacks from webpages."

### 11

- id: 11
- name: MetaGPT shared message pool and subscriptions
- origin: MetaGPT paper, 2023 preprint / ICLR 2024, FoundationAgents
- topology: bus
- shared_state: Structured messages live in one global message pool; role-local memory and generated documents/code files retain consumed outputs.
- wake_rule: Every agent monitors the message-pool environment; a subscribed relevant message can directly trigger that agent's next SOP action.
- wakeups_per_N: NA (no central coordinator)
- coordinator_rereads_context: NA, because roles subscribe directly and the SOP, not a coordinator, advances the assembly line.
- results_return_via: shared store
- parent_blocked_while_child_runs: no
- who_decides_next_task: static graph
- failure_mode_named_in_source: Information overload from excessive or irrelevant messages; subscriptions filter irrelevant context.
- wins_on_task_class: Collaborative software engineering; the paper reports more coherent solutions than prior chat-based multi-agent systems.
- coordination_cost_number: UNKNOWN
- source_url: https://proceedings.iclr.cc/paper_files/paper/2024/file/6507b115562bb0a305f1958ccc87355a-Paper-Conference.pdf
- tier: 2 primary
- quote: "Every agent monitors the environment ... These messages can either directly trigger actions. ... ‘information overload,’ which refers to the problem of receiving excessive or irrelevant information."

### 12

- id: 12
- name: CrewAI sequential process
- origin: CrewAI process documentation, 2024, CrewAI
- topology: pipeline
- shared_state: Task outputs live in the Crew execution context; the next task receives the previous output automatically or selected outputs through `Task.context`.
- wake_rule: The next task starts after the preceding task in the predefined task list completes and supplies its output as context.
- wakeups_per_N: N - 1 (derived)
- coordinator_rereads_context: NA, because the sequential process has no manager agent.
- results_return_via: return value
- parent_blocked_while_child_runs: yes
- who_decides_next_task: static graph
- failure_mode_named_in_source: Crew construction requires `my_agents` and `my_tasks` to be defined before creating the `Crew` object.
- wins_on_task_class: UNKNOWN
- coordination_cost_number: UNKNOWN
- source_url: https://docs.crewai.com/en/concepts/processes
- tier: 2 primary
- quote: "Task execution follows the predefined order ... output of one task serving as context for the next. ... Ensure my_agents and my_tasks are defined prior"

### 13

- id: 13
- name: CrewAI hierarchical process
- origin: CrewAI process documentation, 2024, CrewAI
- topology: tree
- shared_state: Task outputs and completion state live in the Crew runtime and are reviewed by the manager agent before further delegation.
- wake_rule: The manager runs initially to plan and delegate, then reviews every agent output and assesses whether the assigned task is complete.
- wakeups_per_N: N + 1 (derived)
- coordinator_rereads_context: yes, because the manager reviews each output and assesses completion before choosing further work.
- results_return_via: return value
- parent_blocked_while_child_runs: UNKNOWN
- who_decides_next_task: coordinator
- failure_mode_named_in_source: The hierarchical process cannot be enabled unless the crew specifies either `manager_llm` or `manager_agent`.
- wins_on_task_class: UNKNOWN
- coordination_cost_number: UNKNOWN
- source_url: https://docs.crewai.com/en/concepts/processes
- tier: 2 primary
- quote: "manager allocates tasks to agents ... reviews outputs, and assesses task completion. ... a manager language model or a custom manager agent must be specified"

### 14

- id: 14
- name: Google Agent2Agent (A2A) protocol
- origin: Google A2A launch, 2025, Google Cloud; A2A v1.0 specification, 2026, Linux Foundation
- topology: mesh
- shared_state: The remote A2A server manages stateful `Task` objects; `taskId` and `contextId` bind status, history, messages, and artifacts across turns.
- wake_rule: In push-notification mode, the client agent is activated by an HTTP POST whenever the remote task has an update.
- wakeups_per_N: N + K, where K is the number of intermediate status/artifact updates (derived)
- coordinator_rereads_context: NA, because A2A specifies client/server protocol state but does not specify a coordinator model context.
- results_return_via: other
- parent_blocked_while_child_runs: UNKNOWN
- who_decides_next_task: UNKNOWN
- failure_mode_named_in_source: Push-notification deliveries can be duplicated, so clients should process them idempotently.
- wins_on_task_class: Cross-vendor, cross-framework enterprise agent collaboration, including long-running and disconnected tasks.
- coordination_cost_number: UNKNOWN
- source_url: https://a2a-protocol.org/latest/specification/
- tier: 2 primary
- quote: "When a task update occurs, the agent sends an HTTP POST request ... Clients SHOULD process notifications idempotently, as duplicate deliveries may occur."

### 15

- id: 15
- name: MCP sampling
- origin: Model Context Protocol specification 2025-06-18, 2025, Model Context Protocol
- topology: star
- shared_state: The server sends sampling messages and preferences in a JSON-RPC request; model access, selection, permissions, and the generated response remain controlled by the client host.
- wake_rule: The host client invokes its model after an MCP server sends `sampling/createMessage` and any configured human approval permits the request.
- wakeups_per_N: N (derived)
- coordinator_rereads_context: no, because the sampled model receives the request's explicit messages and optional included MCP context, not an implicit server transcript.
- results_return_via: return value
- parent_blocked_while_child_runs: yes
- who_decides_next_task: worker itself
- failure_mode_named_in_source: The user can reject the sampling request, which the client returns as an error.
- wins_on_task_class: Nested agentic behavior in MCP server features without server-side model API keys.
- coordination_cost_number: UNKNOWN
- source_url: https://modelcontextprotocol.io/specification/2025-06-18/client/sampling
- tier: 2 primary
- quote: "To request a language model generation, servers send a sampling/createMessage request. ... User rejected sampling request"

### 16

- id: 16
- name: MCP elicitation
- origin: Model Context Protocol specification 2025-06-18, 2025, Model Context Protocol
- topology: star
- shared_state: The client owns the user-facing interaction and returns schema-validated content in the JSON-RPC response; optional server state is implementation-defined.
- wake_rule: The client asks the user for information when an MCP server sends `elicitation/create` during another server interaction.
- wakeups_per_N: N (derived)
- coordinator_rereads_context: NA, because the coordinating participant is a client UI and user rather than a model agent.
- results_return_via: return value
- parent_blocked_while_child_runs: yes
- who_decides_next_task: worker itself
- failure_mode_named_in_source: The user may decline or cancel; the server must handle those response states instead of assuming acceptance.
- wins_on_task_class: Interactive MCP workflows that need structured user information during tool, resource, or prompt processing.
- coordination_cost_number: UNKNOWN
- source_url: https://modelcontextprotocol.io/specification/2025-06-18/client/elicitation
- tier: 2 primary
- quote: "servers send an elicitation/create request. ... Servers should handle each state appropriately: ... Decline ... Cancel"

### 17

- id: 17
- name: CAMEL role-playing pair
- origin: CAMEL paper, 2023, NeurIPS 2023
- topology: other:dyad
- shared_state: Conversation history `M_t` is passed to the AI User, then the new instruction plus `M_t` is passed to the AI Assistant.
- wake_rule: After each assistant solution, the AI User reads the accumulated history and issues the next instruction; that instruction activates the AI Assistant.
- wakeups_per_N: NA (no N-way parallel round)
- coordinator_rereads_context: yes, because the AI User task planner consumes the full historical message set `M_t` at each step.
- results_return_via: message
- parent_blocked_while_child_runs: yes
- who_decides_next_task: other
- failure_mode_named_in_source: Role flipping, repeated instructions, flake replies, and an infinite loop of messages.
- wins_on_task_class: Instruction-following cooperation and complex task-solving through autonomous role play with minimal human intervention.
- coordination_cost_number: UNKNOWN
- source_url: https://arxiv.org/pdf/2303.17760
- tier: 2 primary
- quote: "The AI user continuously provides instructions to the AI assistant for task-solving. ... role flipping, assistant repeating instructions, flake replies, and infinite loop of messages."
