namespace WindowsVhs;

abstract record TapeCommand;

record OutputCommand(string Filename) : TapeCommand;
record SetCommand(string Property, string Value) : TapeCommand;
record TypeCommand(string Text) : TapeCommand;
record EnterCommand : TapeCommand;
record SleepCommand(TimeSpan Duration) : TapeCommand;
record BackspaceCommand(int Count = 1) : TapeCommand;
record KeyCommand(string Key) : TapeCommand;
record CtrlCommand(char Key) : TapeCommand;
record HideCommand : TapeCommand;
record ShowCommand : TapeCommand;
