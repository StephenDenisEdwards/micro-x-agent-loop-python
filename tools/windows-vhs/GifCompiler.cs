using System.Diagnostics;

namespace WindowsVhs;

static class GifCompiler
{
    public static void Compile(string framesDir, string outputPath, int fps = 10)
    {
        var inputPattern = Path.Combine(framesDir, "frame_%05d.png");

        // Two-pass for high-quality GIF: generate palette then apply it
        var paletteFilter = $"fps={fps},scale=-1:-1:flags=lanczos";
        var palettePath = Path.Combine(framesDir, "palette.png");

        // Pass 1: generate palette
        Run("ffmpeg",
            $"-y -framerate {fps} -i \"{inputPattern}\" " +
            $"-vf \"{paletteFilter},palettegen=stats_mode=diff\" \"{palettePath}\"");

        // Pass 2: apply palette
        Run("ffmpeg",
            $"-y -framerate {fps} -i \"{inputPattern}\" -i \"{palettePath}\" " +
            $"-lavfi \"{paletteFilter} [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=5\" " +
            $"-loop 0 \"{outputPath}\"");

        Console.WriteLine($"Output: {Path.GetFullPath(outputPath)} ({new FileInfo(outputPath).Length / 1024} KB)");
    }

    static void Run(string exe, string args)
    {
        var psi = new ProcessStartInfo
        {
            FileName = exe,
            Arguments = args,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };

        using var process = Process.Start(psi)
            ?? throw new InvalidOperationException($"Failed to start {exe}");

        var stderr = process.StandardError.ReadToEnd();
        process.WaitForExit();

        if (process.ExitCode != 0)
            throw new InvalidOperationException($"{exe} failed (exit {process.ExitCode}):\n{stderr}");
    }
}
