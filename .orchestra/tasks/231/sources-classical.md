### 1

- id: 1
- name: Blackboard architecture (Hearsay-II)
- origin: Erman, Hayes-Roth, Lesser, and Reddy, “The Hearsay-II Speech-Understanding System,” 1980, ACM Computing Surveys 12(2)
- topology: shared-store
- shared_state: The blackboard global database, focus-of-control database, and scheduling queues in the Hearsay-II process
- wake_rule: The scheduler runs at the start of each cycle; relevant blackboard changes cause the monitor to enqueue a knowledge-source condition activity
- wakeups_per_N: N scheduler cycles for N selected knowledge-source activities (derived)
- coordinator_rereads_context: yes, the scheduler uses global-state information to recalculate every queued activity's priority each cycle
- results_return_via: shared store
- parent_blocked_while_child_runs: yes
- who_decides_next_task: coordinator
- failure_mode_named_in_source: Combinatorial explosion of knowledge-source invocations
- wins_on_task_class: Speech understanding with uncertain, ambiguous input and multiple diverse, error-prone knowledge sources
- coordination_cost_number: “the opportunistic strategy took less than half as much processing time”
- source_url: https://mas.cs.umass.edu/Documents/Erman_Hearsay80.pdf
- tier: 2 primary
- quote: “At the start of each cycle, the scheduler [...] calculates a priority for each activity”; “combinatorial explosion of KS invocations that can occur.”

### 2

- id: 2
- name: Contract Net Protocol
- origin: Reid G. Smith, “The Contract Net Protocol,” 1980, IEEE Transactions on Computers C-29(12)
- topology: mesh
- shared_state: Per-node local task, announcement, bid, contract, and task-template data structures; no global shared store
- wake_rule: A manager processes each received bid, awards immediately when a bid is satisfactory, otherwise acts at expiration; it processes final reports from contractors
- wakeups_per_N: at least 2N manager wakeups for N awarded tasks, one accepted bid and one final report per task; extra bids or expirations add wakeups (derived)
- coordinator_rereads_context: yes, the manager reranks each bid against its locally stored ranked bid list
- results_return_via: message
- parent_blocked_while_child_runs: no
- who_decides_next_task: auction
- failure_mode_named_in_source: A task announcement receives no bids
- wins_on_task_class: Distributed problem solving where task allocation needs load balancing and task-specific selection of knowledge sources
- coordination_cost_number: UNKNOWN
- source_url: https://reidgsmith.com/The_Contract_Net_Protocol_Dec-1980.pdf
- tier: 2 primary
- quote: “When a bid is received, the manager ranks the bid [...] Otherwise, the manager waits for further bids”; “a task announcement may not receive any bids.”

### 3

- id: 3
- name: Actor model (Hewitt/Agha mailboxes)
- origin: Gul Agha, “Actors: A Model of Concurrent Computation in Distributed Systems,” MIT AI Laboratory Technical Report 844, 1985; MIT Press edition, 1986
- topology: mesh
- shared_state: Per-actor behavior/state and per-address mail queues physically maintained by the mail system; no global shared state
- wake_rule: An actor activates when it accepts a communication addressed to its mail address from its mail queue
- wakeups_per_N: N actor activations for N accepted task messages (derived)
- coordinator_rereads_context: no, an actor processes a communication with its local behavior rather than rereading global context
- results_return_via: message
- parent_blocked_while_child_runs: no
- who_decides_next_task: worker itself
- failure_mode_named_in_source: Divergence and deadlock in distributed computations
- wins_on_task_class: Dynamically reconfigurable, large-scale parallel and distributed systems
- coordination_cost_number: UNKNOWN
- source_url: https://www.ics.uci.edu/~jajones/INF102-S18/readings/28_Actors-AghaThesis.pdf
- tier: 2 primary
- quote: “When an actor accepts a communication, it may create new actors or tasks”; “Distributed systems often exhibit pathological behavior such as divergence and deadlock.”

### 4

- id: 4
- name: Erlang/OTP supervision trees
- origin: Erlang/OTP Design Principles 4.8.2, OTP Team, 1997, official documentation
- topology: tree
- shared_state: Each supervisor process holds its child specifications and restart-intensity state; worker application state remains in worker processes
- wake_rule: A supervisor reacts when it detects that a supervised child has died and the child's restart type and restart-intensity limit call for restart behavior
- wakeups_per_N: F supervisor reactions, where 0 <= F <= N child deaths under one_for_one supervision (derived)
- coordinator_rereads_context: no, the supervisor uses the exit signal, child specification, and restart counters rather than the child's task context
- results_return_via: message
- parent_blocked_while_child_runs: no
- who_decides_next_task: coordinator
- failure_mode_named_in_source: Restart intensity exceeds MaxR within MaxT, causing the supervisor to shut down its children and die
- wins_on_task_class: Fault-tolerant applications structured as workers and supervisors
- coordination_cost_number: UNKNOWN
- source_url: https://erlang.org/documentation/doc-4.8.2/doc/design_principles/sup_princ.html
- tier: 2 primary
- quote: “If a one_for_one supervisor detects that one its children has died”; “If more than MaxR number of restarts occur [...] the supervisor [...] dies.”

### 5

- id: 5
- name: Tuple spaces / Linda
- origin: David Gelernter, “Generative Communication in Linda,” 1985, ACM Transactions on Programming Languages and Systems 7(1)
- topology: shared-store
- shared_state: Tuples in the tuple space, implemented as the dynamic global name space of the distributed program
- wake_rule: A process suspended in in() or read() becomes runnable when a matching tuple becomes available in tuple space
- wakeups_per_N: N wakeups for N in() consumers supplied one matching result tuple each (derived)
- coordinator_rereads_context: NA, there is no coordinator; tuple matching is performed against the shared tuple space
- results_return_via: shared store
- parent_blocked_while_child_runs: UNKNOWN
- who_decides_next_task: worker itself
- failure_mode_named_in_source: An in() operation suspends when no matching tuple is available
- wins_on_task_class: Systems programming in distributed settings and on integrated network computers
- coordination_cost_number: UNKNOWN
- source_url: https://www.cs.unc.edu/~stotts/COMP590-059-f21/slides/lindaGenerative.pdf
- tier: 2 primary
- quote: “If no matching tuple is available in TS, in( ) suspends until one is available and then proceeds as above.”

### 6

- id: 6
- name: MapReduce
- origin: Jeffrey Dean and Sanjay Ghemawat, “MapReduce: Simplified Data Processing on Large Clusters,” 2004, OSDI '04
- topology: star
- shared_state: Task state and intermediate-file metadata in master memory; intermediate data on worker-local disks; input and final output in GFS
- wake_rule: The master processes task-completion messages and periodic ping responses, and wakes the user program only after all map and reduce tasks complete
- wakeups_per_N: N task-completion-message wakeups in a failure-free round (derived)
- coordinator_rereads_context: yes, the master updates per-task state and intermediate-file locations on completion
- results_return_via: file
- parent_blocked_while_child_runs: yes
- who_decides_next_task: coordinator
- failure_mode_named_in_source: Failure of the single master aborts the MapReduce computation
- wins_on_task_class: Large data-set processing expressible as independent map operations followed by grouped reduce operations
- coordination_cost_number: “about a minute of startup overhead”
- source_url: https://www.usenix.org/event/osdi04/tech/full_papers/dean/dean.pdf
- tier: 2 primary
- quote: “When a map task completes, the worker sends a message to the master”; “our current implementation aborts the MapReduce computation if the master fails.”

### 7

- id: 7
- name: BSP supersteps and barrier synchronisation (Pregel)
- origin: Malewicz et al., “Pregel: A System for Large-Scale Graph Processing,” 2010, ACM SIGMOD
- topology: other:star-mesh
- shared_state: Vertex and edge state plus incoming-message queues partitioned across worker memory; checkpoint state in persistent storage; aggregator values at the master
- wake_rule: At each barrier the master waits for every live worker's response; after all responses it advances the global superstep, or enters recovery if a worker fails
- wakeups_per_N: N worker-response wakeups at one barrier for N workers (derived)
- coordinator_rereads_context: yes, the master maintains the live-worker list, assignments, statistics, aggregator values, and global superstep index
- results_return_via: message
- parent_blocked_while_child_runs: yes
- who_decides_next_task: static graph
- failure_mode_named_in_source: Worker failure loses its assigned partition state and requires reload from the latest checkpoint with repeated supersteps
- wins_on_task_class: Large-scale iterative graph algorithms on clusters of commodity machines
- coordination_cost_number: “more than a fourfold reduction in message traffic by using combiners”
- source_url: https://dsf.berkeley.edu/cs286/papers/pregel-sigmod2010.pdf
- tier: 2 primary
- quote: “the master [...] waits for a response from every worker. If any worker fails, the master enters recovery mode”

### 8

- id: 8
- name: Work stealing (Blumofe–Leiserson / Cilk)
- origin: Robert D. Blumofe and Charles E. Leiserson, “Scheduling Multithreaded Computations by Work Stealing,” 1999, Journal of the ACM 46(5)
- topology: mesh
- shared_state: A ready deque and activation records in each processor's memory; thieves access a selected victim's deque
- wake_rule: When a processor's local ready deque is empty after its thread stalls or dies, it becomes a thief and probes a randomly chosen victim's deque
- wakeups_per_N: 0..N-1 successful steal wakeups plus F failed attempts, where F >= 0 (derived)
- coordinator_rereads_context: NA, there is no coordinator; a thief inspects its local deque and one chosen victim's deque
- results_return_via: shared store
- parent_blocked_while_child_runs: no
- who_decides_next_task: worker itself
- failure_mode_named_in_source: Contention when several thieves select the same victim simultaneously
- wins_on_task_class: Fully strict, dynamically generated multithreaded computations with dependencies
- coordination_cost_number: UNKNOWN
- source_url: https://sites.cs.ucsb.edu/~cappello/190B/papers/CilkJACMp720-blumofe.pdf
- tier: 2 primary
- quote: “If the ready deque is empty [...] the processor begins work stealing”; “contention [...] when several thieves happen to descend on the same victim simultaneously.”

### 9

- id: 9
- name: SEDA staged event-driven architecture
- origin: Matt Welsh, David Culler, and Eric Brewer, “SEDA: An Architecture for Well-Conditioned, Scalable Internet Services,” 2001, SOSP-18
- topology: pipeline
- shared_state: Each stage's private state, incoming event queue, and thread pool; controllers hold per-stage measurements and control parameters
- wake_rule: A stage thread pulls a batch from its incoming event queue; the thread-pool controller periodically samples queue length and adds a thread above its threshold
- wakeups_per_N: between 1 and N stage-handler invocations for N queued events, depending on batch size (derived)
- coordinator_rereads_context: UNKNOWN
- results_return_via: message
- parent_blocked_while_child_runs: no
- who_decides_next_task: static graph
- failure_mode_named_in_source: An unbounded outgoing event queue exhausts memory and crashes the server
- wins_on_task_class: Highly concurrent Internet services subject to large load fluctuations
- coordination_cost_number: UNKNOWN
- source_url: https://people.eecs.berkeley.edu/~brewer/papers/SEDA-sosp.pdf
- tier: 2 primary
- quote: “Stage threads operate by pulling a batch of events off of the incoming event queue”; “server would crash after running out of memory.”

### 10

- id: 10
- name: Publish/subscribe
- origin: Eugster, Felber, Guerraoui, and Kermarrec, “The Many Faces of Publish/Subscribe,” 2003, ACM Computing Surveys 35(2)
- topology: bus
- shared_state: Subscription information stored in the event notification service; event persistence physically varies by broker implementation
- wake_rule: On publish(), the event service asynchronously notifies every subscriber whose stored registered interest matches the event
- wakeups_per_N: sum(matches(event_i), i=1..N) subscriber notification wakeups for N published events (derived)
- coordinator_rereads_context: yes, the event service matches each published event against stored subscription information
- results_return_via: message
- parent_blocked_while_child_runs: no
- who_decides_next_task: other
- failure_mode_named_in_source: Failures prevent subscribers from receiving some matching events
- wins_on_task_class: Loosely coupled distributed interaction in large-scale applications
- coordination_cost_number: UNKNOWN
- source_url: https://cs.brown.edu/courses/cs227/archives/2016/papers/FacesOfPubSub.pdf
- tier: 4 single-secondary
- quote: “The event service propagates the event to all relevant subscribers”; “failures might prevent subscribers from receiving some events.”
