# Worker memory

- Durable keyed `MessageDeliveryContext` advertises `allow_running=True`; `InitialDeliveryContext` does not. `AgentSession.send` uses that distinction to keep initial delivery idle-only while steering keyed receipts without volatile pending state.
