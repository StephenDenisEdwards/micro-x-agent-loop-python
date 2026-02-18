using System.ComponentModel;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Text;
using ModelContextProtocol.Server;

namespace SystemInfo.Tools;

[McpServerToolType]
public static class NetworkInfoTools
{
    [McpServerTool, Description("Get network interface information including IP addresses for this machine")]
    public static string network_info()
    {
        var sb = new StringBuilder();
        sb.AppendLine("Network Interfaces");
        sb.AppendLine("==================");

        var interfaces = NetworkInterface.GetAllNetworkInterfaces()
            .Where(ni => ni.OperationalStatus == OperationalStatus.Up);

        foreach (var ni in interfaces)
        {
            var speedMbps = ni.Speed / 1_000_000;

            sb.AppendLine();
            sb.AppendLine($"{ni.Name}");
            sb.AppendLine($"  Type:   {ni.NetworkInterfaceType}");
            sb.AppendLine($"  Speed:  {speedMbps} Mbps");

            var ipProps = ni.GetIPProperties();
            foreach (var addr in ipProps.UnicastAddresses)
            {
                var family = addr.Address.AddressFamily switch
                {
                    AddressFamily.InterNetwork => "IPv4",
                    AddressFamily.InterNetworkV6 => "IPv6",
                    _ => addr.Address.AddressFamily.ToString()
                };
                sb.AppendLine($"  {family}:   {addr.Address}");
            }
        }

        return sb.ToString().TrimEnd();
    }
}
