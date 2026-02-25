import unittest

from micro_x_agent_loop.tools.bash_tool import BashTool


class BashToolMutationProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = BashTool()

    def test_is_mutating_is_true(self) -> None:
        self.assertTrue(self.tool.is_mutating)

    def test_predict_touched_paths_redirect(self) -> None:
        result = self.tool.predict_touched_paths({"command": "echo hi > out.txt"})
        self.assertEqual(["out.txt"], result)

    def test_predict_touched_paths_rm(self) -> None:
        result = self.tool.predict_touched_paths({"command": "rm -f temp.log"})
        self.assertIn("temp.log", result)

    def test_predict_touched_paths_touch(self) -> None:
        result = self.tool.predict_touched_paths({"command": "touch new_file.txt"})
        self.assertEqual(["new_file.txt"], result)

    def test_predict_touched_paths_read_only(self) -> None:
        result = self.tool.predict_touched_paths({"command": "ls -la"})
        self.assertEqual([], result)

    def test_predict_touched_paths_git_status(self) -> None:
        result = self.tool.predict_touched_paths({"command": "git status"})
        self.assertEqual([], result)

    def test_predict_touched_paths_empty_command(self) -> None:
        result = self.tool.predict_touched_paths({"command": ""})
        self.assertEqual([], result)

    def test_predict_touched_paths_missing_command_key(self) -> None:
        result = self.tool.predict_touched_paths({})
        self.assertEqual([], result)

    def test_predict_touched_paths_non_string_command(self) -> None:
        result = self.tool.predict_touched_paths({"command": 42})
        self.assertEqual([], result)

    def test_predict_touched_paths_chained(self) -> None:
        result = self.tool.predict_touched_paths(
            {"command": "mkdir build && cp src.txt build/src.txt"}
        )
        self.assertIn("build", result)
        self.assertIn("build/src.txt", result)


if __name__ == "__main__":
    unittest.main()
