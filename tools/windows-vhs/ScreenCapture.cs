using System.Drawing;
using System.Drawing.Imaging;

namespace WindowsVhs;

sealed class ScreenCapture : IDisposable
{
    readonly IntPtr _windowHandle;
    readonly string _framesDir;
    readonly int _fps;
    CancellationTokenSource? _cts;
    Task? _captureTask;
    int _frameCount;
    bool _paused;

    public int FrameCount => _frameCount;
    public string FramesDir => _framesDir;

    public ScreenCapture(IntPtr windowHandle, string framesDir, int fps = 10)
    {
        _windowHandle = windowHandle;
        _framesDir = framesDir;
        _fps = fps;
        Directory.CreateDirectory(framesDir);
    }

    public void Start()
    {
        _cts = new CancellationTokenSource();
        _captureTask = Task.Run(() => CaptureLoop(_cts.Token));
    }

    public void Pause() => _paused = true;
    public void Resume() => _paused = false;

    public async Task StopAsync()
    {
        if (_cts is null) return;
        _cts.Cancel();
        if (_captureTask is not null)
            await _captureTask;
        _cts.Dispose();
    }

    void CaptureLoop(CancellationToken ct)
    {
        var interval = TimeSpan.FromMilliseconds(1000.0 / _fps);

        while (!ct.IsCancellationRequested)
        {
            var start = DateTime.UtcNow;

            if (!_paused)
            {
                try
                {
                    CaptureFrame();
                }
                catch
                {
                    // Window may have moved or been minimized — skip frame
                }
            }

            var elapsed = DateTime.UtcNow - start;
            var delay = interval - elapsed;
            if (delay > TimeSpan.Zero)
                Thread.Sleep(delay);
        }
    }

    void CaptureFrame()
    {
        if (!Win32.GetWindowRect(_windowHandle, out var rect))
            return;

        var width = rect.Width;
        var height = rect.Height;
        if (width <= 0 || height <= 0) return;

        using var bitmap = new Bitmap(width, height, PixelFormat.Format32bppArgb);
        using var graphics = Graphics.FromImage(bitmap);
        graphics.CopyFromScreen(rect.Left, rect.Top, 0, 0, new Size(width, height));

        var framePath = Path.Combine(_framesDir, $"frame_{_frameCount:D5}.png");
        bitmap.Save(framePath, ImageFormat.Png);
        _frameCount++;
    }

    public void Dispose()
    {
        if (_cts is null) return;
        if (!_cts.IsCancellationRequested)
        {
            try { _cts.Cancel(); } catch (ObjectDisposedException) { }
        }
        try { _cts.Dispose(); } catch (ObjectDisposedException) { }
    }
}
