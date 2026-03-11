from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from micro_x_agent_loop.manifest import load_manifest


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
                json.dumps({
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
                }),
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


if __name__ == "__main__":
    unittest.main()
