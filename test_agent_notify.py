"""Test: spawn sub-agent via SDK and receive TaskNotification."""

import asyncio
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    PermissionResultAllow,
)
from claude_agent_sdk.types import AgentDefinition, TaskNotificationMessage, TaskProgressMessage, TaskStartedMessage

async def auto_approve(tool_name, tool_input, _context=None):
    print(f"  [tool-approve] {tool_name}")
    return PermissionResultAllow(updated_input=tool_input)

async def main():
    worker_agent = AgentDefinition(
        description="Test worker that counts files",
        prompt="Count Python files in the current directory. Just say the number.",
        model="claude-sonnet-4-6",
        background=True,
        maxTurns=5,
        permissionMode="bypassPermissions",
    )

    options = ClaudeAgentOptions(
        model="claude-sonnet-4-6",
        cwd="/mnt/data/Projects/Python/Parsing/zahoron-mobile",
        max_turns=10,
        permission_mode="bypassPermissions",
        can_use_tool=auto_approve,
        agents={"file-counter": worker_agent},
    )

    client = ClaudeSDKClient(options=options)
    print("Connecting...")
    await client.connect()
    print("Connected. Sending query to spawn agent...")

    await client.query("Use the Agent tool to spawn 'file-counter' agent in background. Then wait for its result.")

    async for msg in client.receive_messages():
        msg_type = type(msg).__name__
        print(f"[{msg_type}]", end=" ")

        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    print(f"TEXT: {block.text[:200]}")
                elif isinstance(block, ToolUseBlock):
                    print(f"TOOL: {block.name}")
        elif isinstance(msg, TaskStartedMessage):
            print(f"TASK STARTED: {msg.task_id} - {msg.description}")
        elif isinstance(msg, TaskProgressMessage):
            print(f"TASK PROGRESS: {msg.task_id} - {msg.description}")
        elif isinstance(msg, TaskNotificationMessage):
            print(f"TASK DONE: {msg.task_id} - status={msg.status} summary={msg.summary[:200]}")
            break
        elif isinstance(msg, ResultMessage):
            print(f"RESULT: cost=${getattr(msg, 'total_cost_usd', 0)}")
            break
        else:
            print(f"other: {msg_type}")

    await client.disconnect()
    print("Done!")

asyncio.run(main())
