using System.ComponentModel;
using System.Runtime.InteropServices;
using ModelContextProtocol.Server;

namespace SystemInfo.Tools;

[McpServerToolType]
public static class SystemInfoTools
{
    [McpServerTool, Description("Get operating system, CPU, memory, and runtime information for this machine")]
    public static string system_info()
    {
        var osDescription = RuntimeInformation.OSDescription;
        var machineName = Environment.MachineName;
        var processorCount = Environment.ProcessorCount;
        var userName = Environment.UserName;
        var runtimeVersion = RuntimeInformation.FrameworkDescription;
        var uptime = TimeSpan.FromMilliseconds(Environment.TickCount64);

        var gcMemInfo = GC.GetGCMemoryInfo();
        var totalMemoryBytes = gcMemInfo.TotalAvailableMemoryBytes;
        var totalMemoryGb = totalMemoryBytes / (1024.0 * 1024 * 1024);

        var process = System.Diagnostics.Process.GetCurrentProcess();
        // Available memory estimate: total minus working sets of running processes is impractical,
        // so we report total memory from GC info which reflects physical RAM.

        return $"""
            System Information
            ==================
            OS:              {osDescription}
            Machine Name:    {machineName}
            Current User:    {userName}
            Processor Count: {processorCount}
            Total Memory:    {totalMemoryGb:F1} GB
            System Uptime:   {uptime.Days}d {uptime.Hours}h {uptime.Minutes}m
            .NET Runtime:    {runtimeVersion}
            """;
    }
}
