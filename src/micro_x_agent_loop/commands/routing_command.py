"""`/routing` — semantic-routing statistics command."""

from __future__ import annotations

from micro_x_agent_loop.commands.command_context import CommandContext


async def handle_routing(ctx: CommandContext, command: str) -> None:
    p = ctx.line_prefix
    if ctx.routing_feedback_store is None:
        ctx.print(f"{p}Routing stats require SemanticRoutingEnabled=true and RoutingFeedbackEnabled=true")
        return

    from micro_x_agent_loop.routing_feedback import RoutingFeedbackStore

    store: RoutingFeedbackStore = ctx.routing_feedback_store  # type: ignore[assignment]

    parts = command.split()
    sub = parts[1] if len(parts) >= 2 else ""

    if sub == "tasks":
        stats = store.get_task_type_stats()
        if not stats:
            ctx.print(f"{p}No routing data recorded yet.")
            return
        ctx.print(f"{p}Routing stats by task type:")
        ctx.print(
            f"{p}{'Task Type':<20s} {'Count':>6s} {'Avg Cost':>10s}"
            f" {'Avg Latency':>12s} {'Avg Conf':>9s} {'+ / -':>7s}"
        )
        for s in stats:
            ctx.print(
                f"{p}{s['task_type']:<20s} {s['total']:>6d} "
                f"${s['avg_cost']:.4f}  {s['avg_latency']:>8.0f} ms  "
                f"{s['avg_confidence']:.2f}   "
                f"{s['positive_signals']:>3d}/{s['negative_signals']:<3d}"
            )
        return

    if sub == "providers":
        stats = store.get_provider_stats()
        if not stats:
            ctx.print(f"{p}No routing data recorded yet.")
            return
        ctx.print(f"{p}Routing stats by provider:")
        ctx.print(
            f"{p}{'Provider':<15s} {'Count':>6s} {'Avg Cost':>10s}"
            f" {'Avg Latency':>12s} {'Errors':>7s} {'Total Cost':>11s}"
        )
        for s in stats:
            ctx.print(
                f"{p}{s['provider']:<15s} {s['total']:>6d} "
                f"${s['avg_cost']:.4f}  {s['avg_latency']:>8.0f} ms  "
                f"{s['errors']:>7d} ${s['total_cost']:.4f}"
            )
        return

    if sub == "stages":
        stats = store.get_stage_stats()
        if not stats:
            ctx.print(f"{p}No routing data recorded yet.")
            return
        ctx.print(f"{p}Classification stage breakdown:")
        for s in stats:
            ctx.print(
                f"{p}  {s['stage']}: {s['total']} calls "
                f"({s['percentage']:.1f}%), avg confidence {s['avg_confidence']:.2f}"
            )
        return

    if sub == "recent":
        outcomes = store.get_recent_outcomes(20)
        if not outcomes:
            ctx.print(f"{p}No routing data recorded yet.")
            return
        ctx.print(f"{p}Recent routing decisions:")
        for o in outcomes:
            ctx.print(
                f"{p}  T{o['turn_number']} {o['task_type']:<18s}"
                f" {o['provider']}/{o['model']:<20s}"
                f" stage={o['stage']} conf={o['confidence']:.2f}"
                f" ${o['cost_usd']:.4f}"
            )
        return

    # Default: summary view
    task_stats = store.get_task_type_stats()
    if not task_stats:
        ctx.print(f"{p}No routing data recorded yet.")
        ctx.print(
            f"{p}Usage: /routing | /routing tasks | /routing providers | /routing stages | /routing recent"
        )
        return

    total_calls = sum(s["total"] for s in task_stats)
    total_cost = sum(s["total_cost"] for s in task_stats)
    ctx.print(f"{p}Semantic Routing Summary")
    ctx.print(f"{p}  Total routed calls: {total_calls}")
    ctx.print(f"{p}  Total routed cost:  ${total_cost:.4f}")
    ctx.print(f"{p}  Task types active:  {len(task_stats)}")

    stage_stats = store.get_stage_stats()
    for s in stage_stats:
        ctx.print(f"{p}  Stage {s['stage']}: {s['percentage']:.1f}% of calls")

    ctx.print(f"{p}Use /routing tasks|providers|stages|recent for details.")
