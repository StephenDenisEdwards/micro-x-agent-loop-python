namespace WindowsVhs;

static class TapeParser
{
    public static List<TapeCommand> Parse(string filePath)
    {
        var commands = new List<TapeCommand>();

        foreach (var rawLine in File.ReadLines(filePath))
        {
            var line = rawLine.Trim();
            if (string.IsNullOrEmpty(line) || line.StartsWith('#'))
                continue;

            var command = ParseLine(line)
                ?? throw new FormatException($"Unknown tape command: {line}");
            commands.Add(command);
        }

        return commands;
    }

    static TapeCommand? ParseLine(string line)
    {
        if (TryParseKeyword(line, "Output", out var arg))
            return new OutputCommand(arg);

        if (TryParseKeyword(line, "Set", out arg))
        {
            var spaceIdx = arg.IndexOf(' ');
            if (spaceIdx < 0) throw new FormatException($"Invalid Set command: {line}");
            return new SetCommand(arg[..spaceIdx], arg[(spaceIdx + 1)..].Trim());
        }

        if (TryParseKeyword(line, "Type", out arg))
            return new TypeCommand(Unquote(arg));

        if (line == "Enter")
            return new EnterCommand();

        if (TryParseKeyword(line, "Sleep", out arg))
            return new SleepCommand(ParseDuration(arg));

        if (line == "Backspace")
            return new BackspaceCommand();

        if (TryParseKeyword(line, "Backspace", out arg) && int.TryParse(arg, out var count))
            return new BackspaceCommand(count);

        if (line == "Hide")
            return new HideCommand();

        if (line == "Show")
            return new ShowCommand();

        if (TryParseKeyword(line, "Ctrl+", out arg) && arg.Length == 1)
            return new CtrlCommand(arg[0]);

        var simpleKeys = new[] { "Up", "Down", "Left", "Right", "Tab", "Space", "Escape" };
        if (simpleKeys.Contains(line))
            return new KeyCommand(line);

        return null;
    }

    static bool TryParseKeyword(string line, string keyword, out string argument)
    {
        if (line.StartsWith(keyword + " ", StringComparison.Ordinal) ||
            line.StartsWith(keyword, StringComparison.Ordinal) && keyword.EndsWith('+'))
        {
            argument = line[(keyword.Length + (keyword.EndsWith('+') ? 0 : 1))..].Trim();
            return true;
        }
        argument = "";
        return false;
    }

    static string Unquote(string s)
    {
        if (s.Length >= 2 && s[0] == '"' && s[^1] == '"')
            return s[1..^1].Replace("\\\"", "\"").Replace("\\n", "\n").Replace("\\\\", "\\");
        return s;
    }

    static TimeSpan ParseDuration(string s)
    {
        s = s.Trim();
        if (s.EndsWith("ms") && double.TryParse(s[..^2], out var ms))
            return TimeSpan.FromMilliseconds(ms);
        if (s.EndsWith("s") && double.TryParse(s[..^1], out var sec))
            return TimeSpan.FromSeconds(sec);
        if (s.EndsWith("m") && double.TryParse(s[..^1], out var min))
            return TimeSpan.FromMinutes(min);
        throw new FormatException($"Invalid duration: {s}");
    }
}
