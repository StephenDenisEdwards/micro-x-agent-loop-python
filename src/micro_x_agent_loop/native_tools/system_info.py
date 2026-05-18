"""Native port of the system-info MCP server (was a separate .NET server).

Three read-only tools — system_info / disk_info / network_info — exposed
under the same fully-qualified names the MCP version used
(``system-info__<tool>``) so nothing referencing them breaks.

Uses psutil for cross-platform system/disk/network introspection. If
psutil is unavailable the tools degrade to an informative error result
rather than breaking agent bootstrap.
"""

from __future__ import annotations

import getpass
import platform
import time
from typing import Any

from micro_x_agent_loop.tool import Tool, ToolResult

_SERVER = "system-info"
_NO_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


class _NativeReadTool:
    """Base for parameterless, read-only native tools."""

    _tool: str = ""
    _desc: str = ""

    @property
    def name(self) -> str:
        return f"{_SERVER}__{self._tool}"

    @property
    def description(self) -> str:
        return self._desc

    @property
    def input_schema(self) -> dict[str, Any]:
        return _NO_INPUT_SCHEMA

    @property
    def is_mutating(self) -> bool:
        return False

    def predict_touched_paths(self, tool_input: dict[str, Any]) -> list[str]:
        return []

    async def execute(self, tool_input: dict[str, Any]) -> ToolResult:
        try:
            return ToolResult(text=self._render())
        except Exception as ex:  # never break the turn over an info tool
            return ToolResult(text=f"{self._tool} failed: {ex}", is_error=True)

    def _render(self) -> str:  # overridden
        raise NotImplementedError


def _require_psutil() -> Any:
    try:
        import psutil  # noqa: PLC0415

        return psutil
    except ImportError as ex:  # pragma: no cover
        raise RuntimeError(
            "psutil is required for system-info native tools "
            "(pip install -e . — psutil is in pyproject dependencies)"
        ) from ex


class SystemInfoTool(_NativeReadTool):
    _tool = "system_info"
    _desc = "Get operating system, CPU, memory, and runtime information for this machine"

    def _render(self) -> str:
        psutil = _require_psutil()
        vm = psutil.virtual_memory()
        total_gb = vm.total / (1024.0**3)
        uptime_s = int(time.time() - psutil.boot_time())
        days, rem = divmod(uptime_s, 86400)
        hours, rem = divmod(rem, 3600)
        mins = rem // 60
        return (
            "System Information\n"
            "==================\n"
            f"OS:              {platform.platform()}\n"
            f"Machine Name:    {platform.node()}\n"
            f"Current User:    {getpass.getuser()}\n"
            f"Processor Count: {psutil.cpu_count(logical=True)}\n"
            f"Total Memory:    {total_gb:.1f} GB\n"
            f"System Uptime:   {days}d {hours}h {mins}m\n"
            f"Python Runtime:  {platform.python_implementation()} {platform.python_version()}"
        )


class DiskInfoTool(_NativeReadTool):
    _tool = "disk_info"
    _desc = "Get disk usage information for all fixed drives on this machine"

    def _render(self) -> str:
        psutil = _require_psutil()
        lines = ["Disk Information", "================"]
        for part in psutil.disk_partitions(all=False):
            opts = part.opts or ""
            # Skip removable/CD drives (mirror the .NET DriveType.Fixed filter)
            if "cdrom" in opts or part.fstype == "":
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            total_gb = usage.total / (1024.0**3)
            free_gb = usage.free / (1024.0**3)
            used_pct = usage.percent
            lines += [
                "",
                f"Drive {part.device}",
                f"  Mountpoint:  {part.mountpoint}",
                f"  Format:      {part.fstype}",
                f"  Total Size:  {total_gb:.1f} GB",
                f"  Free Space:  {free_gb:.1f} GB",
                f"  Used:        {used_pct:.1f}%",
            ]
        return "\n".join(lines)


class NetworkInfoTool(_NativeReadTool):
    _tool = "network_info"
    _desc = "Get network interface information including IP addresses for this machine"

    def _render(self) -> str:
        import socket  # noqa: PLC0415

        psutil = _require_psutil()
        lines = ["Network Interfaces", "=================="]
        stats = psutil.net_if_stats()
        for name, addrs in psutil.net_if_addrs().items():
            st = stats.get(name)
            if st is None or not st.isup:
                continue
            speed = f"{st.speed} Mbps" if st.speed else "unknown"
            lines += ["", f"{name}", f"  Speed:  {speed}"]
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    lines.append(f"  IPv4:   {addr.address}")
                elif addr.family == socket.AF_INET6:
                    lines.append(f"  IPv6:   {addr.address.split('%')[0]}")
        return "\n".join(lines)


def build_system_info_tools() -> list[Tool]:
    return [SystemInfoTool(), DiskInfoTool(), NetworkInfoTool()]
