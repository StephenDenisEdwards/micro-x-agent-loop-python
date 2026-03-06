from __future__ import annotations

from pathlib import Path


class PromptCommandStore:
    """Discovers and loads prompt commands from a .commands directory."""

    def __init__(self, commands_dir: Path) -> None:
        self._commands_dir = commands_dir

    def list_commands(self) -> list[tuple[str, str]]:
        """Return sorted list of (name, description) for all .md files."""
        if not self._commands_dir.is_dir():
            return []
        results: list[tuple[str, str]] = []
        for path in sorted(self._commands_dir.iterdir()):
            if path.suffix != ".md":
                continue
            name = path.stem
            description = self._read_first_line(path)
            results.append((name, description))
        return results

    def load_command(self, name: str) -> str | None:
        """Load the full prompt text for a command. Returns None if not found."""
        path = self._commands_dir / f"{name}.md"
        if not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def _read_first_line(self, path: Path) -> str:
        try:
            text = path.read_text(encoding="utf-8")
            first_line = text.split("\n", 1)[0].strip()
            return first_line or "(no description)"
        except OSError:
            return "(unreadable)"
