using System.ComponentModel;
using System.Text;
using ModelContextProtocol.Server;

namespace SystemInfo.Tools;

[McpServerToolType]
public static class DiskInfoTools
{
    [McpServerTool, Description("Get disk usage information for all fixed drives on this machine")]
    public static string disk_info()
    {
        var sb = new StringBuilder();
        sb.AppendLine("Disk Information");
        sb.AppendLine("================");

        var drives = DriveInfo.GetDrives()
            .Where(d => d.DriveType == DriveType.Fixed && d.IsReady);

        foreach (var drive in drives)
        {
            var totalGb = drive.TotalSize / (1024.0 * 1024 * 1024);
            var freeGb = drive.TotalFreeSpace / (1024.0 * 1024 * 1024);
            var usedGb = totalGb - freeGb;
            var usedPercent = totalGb > 0 ? (usedGb / totalGb) * 100 : 0;

            sb.AppendLine();
            sb.AppendLine($"Drive {drive.Name}");
            sb.AppendLine($"  Label:       {drive.VolumeLabel}");
            sb.AppendLine($"  Format:      {drive.DriveFormat}");
            sb.AppendLine($"  Total Size:  {totalGb:F1} GB");
            sb.AppendLine($"  Free Space:  {freeGb:F1} GB");
            sb.AppendLine($"  Used:        {usedPercent:F1}%");
        }

        return sb.ToString().TrimEnd();
    }
}
