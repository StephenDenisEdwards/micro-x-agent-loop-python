"""`/debug show-api-payload [N]` — inspect a recorded provider request."""

from __future__ import annotations

from datetime import datetime

from micro_x_agent_loop.commands.command_context import CommandContext


async def handle_debug(ctx: CommandContext, command: str) -> None:
    p = ctx.line_prefix
    parts = command.split()
    if len(parts) >= 2 and parts[1] == "show-api-payload":
        index = 0
        if len(parts) >= 3:
            try:
                index = int(parts[2])
            except ValueError:
                ctx.print(f"{p}Usage: /debug show-api-payload [N]")
                return
        _print_api_payload(ctx, index)
        return
    ctx.print(f"{p}Usage: /debug show-api-payload [N]")


def _print_api_payload(ctx: CommandContext, index: int) -> None:
    from micro_x_agent_loop.usage import estimate_cost

    p = ctx.line_prefix
    payload = ctx.api_payload_store.get(index)
    if payload is None:
        if len(ctx.api_payload_store) == 0:
            ctx.print(f"{p}No API payloads recorded yet.")
        else:
            ctx.print(
                f"{p}Payload index {index} out of range "
                f"(0..{len(ctx.api_payload_store) - 1})."
            )
        return

    ts = datetime.fromtimestamp(payload.timestamp).strftime("%Y-%m-%d %H:%M:%S")

    last_user_msg = ""
    for msg in reversed(payload.messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            last_user_msg = content
            break
        if isinstance(content, list):
            if any(b.get("type") == "tool_result" for b in content if isinstance(b, dict)):
                continue
            texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            last_user_msg = " ".join(texts)
            break

    response_text = ""
    if payload.response_message:
        resp_content = payload.response_message.get("content", [])
        if isinstance(resp_content, str):
            response_text = resp_content
        elif isinstance(resp_content, list):
            texts = [b.get("text", "") for b in resp_content if isinstance(b, dict) and b.get("type") == "text"]
            tool_names = [
                b.get("name", "") for b in resp_content if isinstance(b, dict) and b.get("type") == "tool_use"
            ]
            if texts:
                response_text = " ".join(texts)
            if tool_names:
                tool_label = "tool_use: " + ", ".join(tool_names)
                response_text = f"{response_text}  [{tool_label}]" if response_text else f"[{tool_label}]"

    usage_str = "n/a"
    cost_str = ""
    if payload.usage:
        u = payload.usage
        usage_str = f"in={u.input_tokens} out={u.output_tokens}"
        if u.cache_read_input_tokens:
            usage_str += f" cache_read={u.cache_read_input_tokens}"
        if u.cache_creation_input_tokens:
            usage_str += f" cache_create={u.cache_creation_input_tokens}"
        cost = estimate_cost(u)
        cost_str = f"${cost:.6f}" if cost > 0 else "n/a (unknown model)"

    ctx.print(f"{p}API Payload #{index} (most recent):" if index == 0 else f"{p}API Payload #{index}:")
    ctx.print(f"{p}  Timestamp:    {ts}")
    ctx.print(f"{p}  Model:        {payload.model}")
    ctx.print(f"{p}  System prompt: {payload.system_prompt[:80]}... ({len(payload.system_prompt)} chars)")
    ctx.print(f"{p}  Messages:     {len(payload.messages)}")
    ctx.print(f"{p}  Last user msg: {last_user_msg[:80]}")
    ctx.print(f"{p}  Tools:        {payload.tools_count}")
    ctx.print(f"{p}  Stop reason:  {payload.stop_reason}")
    ctx.print(f"{p}  Response:     {response_text[:80]}... ({len(response_text)} chars)")
    ctx.print(f"{p}  Usage:        {usage_str}")
    ctx.print(f"{p}  Cost:         {cost_str}")
