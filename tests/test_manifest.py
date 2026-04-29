from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from micro_x_agent_loop.manifest import ManifestTool, load_manifest


class ManifestTests(unittest.TestCase):
    def test_load_manifest_injects_resolved_config_into_server_env(self) -> None:
        project_root = Path.cwd() / ".tmp-run" / "manifest-test"
        if project_root.exists():
            shutil.rmtree(project_root)
        try:
            task_dir = project_root / "tools" / "demo_task"
            task_dir.mkdir(parents=True)
            manifest_path = project_root / "tools" / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "demo_task": {
                            "tool_name": "demo_tool",
                            "description": "Demo tool",
                            "server": {
                                "transport": "stdio",
                                "command": "npx",
                                "args": ["tsx", "src/index.ts"],
                                "cwd": "tools/demo_task/",
                                "env": {"EXISTING": "1"},
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )

            resolved_config = {
                "WorkingDirectory": "C:\\work",
                "McpServers": {"google": {"command": "node", "args": ["google.js"]}},
            }

            tools = load_manifest(
                project_root,
                connect_fn=lambda *_args, **_kwargs: None,
                resolved_config=resolved_config,
            )

            self.assertEqual(1, len(tools))
            server_config = tools[0]._server_config
            self.assertEqual(str(task_dir.resolve()), server_config["cwd"])
            self.assertEqual("1", server_config["env"]["EXISTING"])
            self.assertEqual(
                resolved_config,
                json.loads(server_config["env"]["MICRO_X_AGENT_CONFIG_JSON"]),
            )
        finally:
            if project_root.exists():
                shutil.rmtree(project_root)


class ManifestToolPropertiesTests(unittest.TestCase):
    def _make_tool(self, **kwargs: Any) -> ManifestTool:
        defaults = dict(
            task_name="task",
            tool_name="tool",
            description="desc",
            server_config={},
            connect_fn=lambda *a: None,
        )
        defaults.update(kwargs)
        return ManifestTool(**defaults)

    def test_name_is_proxy_name(self) -> None:
        self.assertEqual("task__tool", self._make_tool().name)

    def test_description(self) -> None:
        self.assertEqual("my desc", self._make_tool(description="my desc").description)

    def test_input_schema_is_open_object(self) -> None:
        self.assertEqual("object", self._make_tool().input_schema["type"])

    def test_is_mutating_default_true(self) -> None:
        self.assertTrue(self._make_tool().is_mutating)

    def test_predict_touched_paths_empty(self) -> None:
        self.assertEqual([], self._make_tool().predict_touched_paths({}))


class ManifestToolExecuteTests(unittest.TestCase):
    def test_execute_connects_and_delegates(self) -> None:
        class FakeRealTool:
            name = "task__tool"

            async def execute(self, tool_input: dict) -> Any:
                from micro_x_agent_loop.tool import ToolResult

                return ToolResult(text="done")

        async def fake_connect(task_name: str, config: dict) -> list:
            return [FakeRealTool()]

        tool = ManifestTool(
            task_name="task",
            tool_name="tool",
            description="",
            server_config={},
            connect_fn=fake_connect,
        )
        result = asyncio.run(tool.execute({"input": "test"}))
        self.assertEqual("done", result.text)

    def test_execute_connect_failure(self) -> None:
        async def failing_connect(task_name: str, config: dict) -> list:
            raise RuntimeError("Connection failed")

        tool = ManifestTool(
            task_name="task",
            tool_name="tool",
            description="",
            server_config={},
            connect_fn=failing_connect,
        )
        result = asyncio.run(tool.execute({}))
        self.assertTrue(result.is_error)
        self.assertIn("failed to connect", result.text.lower())

    def test_execute_tool_not_found(self) -> None:
        class OtherTool:
            name = "task__other"

        async def connect(task_name: str, config: dict) -> list:
            return [OtherTool()]

        tool = ManifestTool(
            task_name="task",
            tool_name="tool",
            description="",
            server_config={},
            connect_fn=connect,
        )
        result = asyncio.run(tool.execute({}))
        self.assertTrue(result.is_error)
        self.assertIn("not found", result.text.lower())


class LoadManifestEdgeCaseTests(unittest.TestCase):
    def test_no_manifest_file_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = load_manifest(Path(tmp), lambda *a: None)
            self.assertEqual([], result)

    def test_skips_missing_task_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools_dir = root / "tools"
            tools_dir.mkdir()
            manifest = {"missing": {"tool_name": "t", "description": "d", "server": {"cwd": "tasks/nope"}}}
            (tools_dir / "manifest.json").write_text(json.dumps(manifest))
            result = load_manifest(root, lambda *a: None)
            self.assertEqual([], result)

    def test_invalid_json_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools_dir = root / "tools"
            tools_dir.mkdir()
            (tools_dir / "manifest.json").write_text("not json")
            result = load_manifest(root, lambda *a: None)
            self.assertEqual([], result)


if __name__ == "__main__":
    unittest.main()
