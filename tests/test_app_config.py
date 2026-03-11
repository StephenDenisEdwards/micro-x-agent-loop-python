import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from micro_x_agent_loop.app_config import (
    _expand_env_vars,
    _resolve_config_with_base,
    _to_bool,
    load_json_config,
    resolve_runtime_env,
)


class ToBoolTests(unittest.TestCase):
    """Tests for the _to_bool helper."""

    def test_true_strings(self) -> None:
        for value in ("1", "true", "True", "TRUE", "yes", "YES", "on", "ON", " true "):
            with self.subTest(value=value):
                self.assertIs(_to_bool(value), True)

    def test_false_strings(self) -> None:
        for value in ("0", "false", "False", "FALSE", "no", "NO", "off", "OFF", " false "):
            with self.subTest(value=value):
                self.assertIs(_to_bool(value), False)

    def test_none_returns_default(self) -> None:
        self.assertIs(_to_bool(None), False)
        self.assertIs(_to_bool(None, default=True), True)

    def test_bool_passthrough(self) -> None:
        self.assertIs(_to_bool(True), True)
        self.assertIs(_to_bool(False), False)

    def test_unrecognized_string_raises(self) -> None:
        with self.assertRaises(ValueError):
            _to_bool("maybe")
        with self.assertRaises(ValueError):
            _to_bool("2")
        with self.assertRaises(ValueError):
            _to_bool("")

    def test_int_uses_truthiness(self) -> None:
        self.assertIs(_to_bool(1), True)
        self.assertIs(_to_bool(0), False)
        self.assertIs(_to_bool(42), True)


class ExpandEnvVarsTests(unittest.TestCase):
    """Tests for _expand_env_vars."""

    def test_expands_string(self) -> None:
        os.environ["_TEST_VAR_XYZ"] = "/tmp/test"
        try:
            self.assertEqual(_expand_env_vars("${_TEST_VAR_XYZ}/sub"), "/tmp/test/sub")
        finally:
            del os.environ["_TEST_VAR_XYZ"]

    def test_preserves_unset_var(self) -> None:
        result = _expand_env_vars("${_NONEXISTENT_VAR_12345}")
        self.assertEqual(result, "${_NONEXISTENT_VAR_12345}")

    def test_recurses_into_dicts_and_lists(self) -> None:
        os.environ["_TV"] = "val"
        try:
            data = {"key": "${_TV}", "nested": {"inner": ["${_TV}"]}}
            result = _expand_env_vars(data)
            self.assertEqual(result, {"key": "val", "nested": {"inner": ["val"]}})
        finally:
            del os.environ["_TV"]

    def test_non_string_passthrough(self) -> None:
        self.assertEqual(_expand_env_vars(42), 42)
        self.assertIs(_expand_env_vars(True), True)
        self.assertIsNone(_expand_env_vars(None))


class ResolveConfigWithBaseTests(unittest.TestCase):
    """Tests for _resolve_config_with_base and base config merging."""

    def test_no_base_returns_data_unchanged(self) -> None:
        data = {"Provider": "anthropic", "Model": "claude"}
        result = _resolve_config_with_base(data, Path("."))
        self.assertEqual(result, data)

    def test_base_merge_and_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir) / "base.json"
            base_path.write_text(json.dumps({
                "Provider": "anthropic",
                "Model": "base-model",
                "MaxTokens": 8192,
                "ToolFormatting": {"tool_a": {"format": "json"}},
            }))
            variant = {
                "Base": "base.json",
                "Model": "override-model",
                "PromptCachingEnabled": True,
            }
            result = _resolve_config_with_base(variant, Path(tmpdir))
            # Overlay wins for Model
            self.assertEqual(result["Model"], "override-model")
            # Base value preserved for MaxTokens
            self.assertEqual(result["MaxTokens"], 8192)
            # New key from overlay
            self.assertTrue(result["PromptCachingEnabled"])
            # Base nested dict preserved
            self.assertEqual(result["ToolFormatting"], {"tool_a": {"format": "json"}})
            # Base key removed
            self.assertNotIn("Base", result)

    def test_deep_merge_nested_dicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir) / "base.json"
            base_path.write_text(json.dumps({
                "McpServers": {
                    "filesystem": {"command": "node", "args": ["fs.js"]},
                    "web": {"command": "node", "args": ["web.js"]},
                },
            }))
            variant = {
                "Base": "base.json",
                "McpServers": {
                    "filesystem": {"command": "node", "args": ["fs-v2.js"]},
                },
            }
            result = _resolve_config_with_base(variant, Path(tmpdir))
            # Overlay for filesystem
            self.assertEqual(result["McpServers"]["filesystem"]["args"], ["fs-v2.js"])
            # Base for web preserved
            self.assertEqual(result["McpServers"]["web"]["args"], ["web.js"])

    def test_missing_base_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data = {"Base": "nonexistent.json"}
            with self.assertRaises(FileNotFoundError):
                _resolve_config_with_base(data, Path(tmpdir))


class LoadJsonConfigWithBaseTests(unittest.TestCase):
    """Integration tests for load_json_config with Base field."""

    def test_load_with_base_and_env_expansion(self) -> None:
        os.environ["_TEST_DIR"] = "/tmp/test_dir"
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                base_path = Path(tmpdir) / "base.json"
                base_path.write_text(json.dumps({
                    "Provider": "anthropic",
                    "WorkingDirectory": "${_TEST_DIR}",
                    "MaxTokens": 8192,
                }))
                variant_path = Path(tmpdir) / "variant.json"
                variant_path.write_text(json.dumps({
                    "Base": "base.json",
                    "Model": "claude-haiku",
                }))
                data, path = load_json_config(str(variant_path))
                self.assertEqual(data["Model"], "claude-haiku")
                self.assertEqual(data["MaxTokens"], 8192)
                self.assertEqual(data["WorkingDirectory"], "/tmp/test_dir")
        finally:
            del os.environ["_TEST_DIR"]


class LoadJsonConfigExtraTests(unittest.TestCase):
    def test_load_config_path_not_found(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_json_config("/nonexistent/path/config.json")

    def test_load_no_path_no_cwd_config(self) -> None:
        """When config_path=None and no cwd config.json, returns empty dict."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            orig_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                data, path = load_json_config(None)
                self.assertEqual({}, data)
            finally:
                os.chdir(orig_cwd)

    def test_load_no_path_with_cwd_config(self) -> None:
        """When config_path=None and cwd has config.json, reads it."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "config.json").write_text(json.dumps({"Model": "test-model"}))
            orig_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                data, path = load_json_config(None)
                self.assertEqual("test-model", data.get("Model"))
            finally:
                os.chdir(orig_cwd)

    def test_load_config_file_indirection(self) -> None:
        """config.json with ConfigFile key redirects to another file."""
        with tempfile.TemporaryDirectory() as tmp:
            actual = Path(tmp) / "actual.json"
            actual.write_text(json.dumps({"Provider": "anthropic", "Model": "actual-model"}))
            config_json = Path(tmp) / "config.json"
            config_json.write_text(json.dumps({"ConfigFile": "actual.json"}))

            orig_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                data, path = load_json_config(None)
                self.assertEqual("actual-model", data.get("Model"))
            finally:
                os.chdir(orig_cwd)

    def test_load_config_file_target_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_json = Path(tmp) / "config.json"
            config_json.write_text(json.dumps({"ConfigFile": "nonexistent.json"}))

            orig_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with self.assertRaises(FileNotFoundError):
                    load_json_config(None)
            finally:
                os.chdir(orig_cwd)

    def test_shipped_no_console_profiles_do_not_enable_console_logging(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        for config_name in (
            "config-standard-sonnet-no-console.json",
            "config-standard-openai-no-console.json",
        ):
            with self.subTest(config_name=config_name):
                data, _ = load_json_config(str(repo_root / config_name))
                consumer_types = [item.get("type") for item in data.get("LogConsumers", [])]
                self.assertNotIn("console", consumer_types)


class ResolveRuntimeEnvTests(unittest.TestCase):
    def test_anthropic_provider(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            env = resolve_runtime_env("anthropic")
            self.assertEqual("test-key", env.provider_api_key)
            self.assertEqual("ANTHROPIC_API_KEY", env.provider_env_var)

    def test_openai_provider(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "openai-key"}):
            env = resolve_runtime_env("openai")
            self.assertEqual("openai-key", env.provider_api_key)
            self.assertEqual("OPENAI_API_KEY", env.provider_env_var)


if __name__ == "__main__":
    unittest.main()
