import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from micro_x_agent_loop.app_config import (
    ToolResultOverride,
    _expand_config_refs,
    _expand_env_vars,
    _parse_tool_result_overrides,
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


class ParseToolResultOverridesTests(unittest.TestCase):
    """Tests for _parse_tool_result_overrides."""

    def test_none_returns_empty(self) -> None:
        self.assertEqual(_parse_tool_result_overrides(None), {})

    def test_non_dict_returns_empty(self) -> None:
        self.assertEqual(_parse_tool_result_overrides("not-a-dict"), {})
        self.assertEqual(_parse_tool_result_overrides([1, 2, 3]), {})

    def test_full_entry(self) -> None:
        result = _parse_tool_result_overrides({
            "gmail_read": {"Summarize": False, "Threshold": 10000, "MaxChars": 200000},
        })
        self.assertEqual(
            result,
            {"gmail_read": ToolResultOverride(summarize=False, threshold=10000, max_chars=200000)},
        )

    def test_partial_entry_leaves_other_fields_none(self) -> None:
        result = _parse_tool_result_overrides({"web_fetch": {"Summarize": False}})
        self.assertEqual(
            result,
            {"web_fetch": ToolResultOverride(summarize=False, threshold=None, max_chars=None)},
        )

    def test_summarize_accepts_string_bools(self) -> None:
        result = _parse_tool_result_overrides({"x": {"Summarize": "true"}})
        self.assertIs(result["x"].summarize, True)

    def test_unknown_inner_keys_ignored(self) -> None:
        result = _parse_tool_result_overrides({
            "x": {"Summarize": False, "BogusKey": 42},
        })
        self.assertEqual(result["x"], ToolResultOverride(summarize=False))

    def test_non_dict_entry_skipped(self) -> None:
        result = _parse_tool_result_overrides({
            "good": {"Summarize": False},
            "bad": "should be a dict",
        })
        self.assertEqual(set(result.keys()), {"good"})

    def test_negative_threshold_dropped(self) -> None:
        result = _parse_tool_result_overrides({"x": {"Threshold": -5, "MaxChars": 100}})
        self.assertEqual(result["x"], ToolResultOverride(threshold=None, max_chars=100))

    def test_negative_max_chars_dropped(self) -> None:
        result = _parse_tool_result_overrides({"x": {"MaxChars": -1}})
        self.assertEqual(result["x"], ToolResultOverride(max_chars=None))

    def test_multiple_tools(self) -> None:
        result = _parse_tool_result_overrides({
            "gmail_read": {"Summarize": False, "MaxChars": 200000},
            "web_fetch": {"Summarize": False, "MaxChars": 200000},
            "gmail_search": {"Summarize": True, "Threshold": 20000},
        })
        self.assertEqual(len(result), 3)
        self.assertEqual(
            result["gmail_search"],
            ToolResultOverride(summarize=True, threshold=20000),
        )


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


class ExpandConfigRefsTests(unittest.TestCase):
    """Tests for _expand_config_refs (#KeyName self-references)."""

    def test_resolves_ref_to_same_config_key(self) -> None:
        data = {"Model": "claude-sonnet-4-5-20250929", "SubAgentModel": "#Model"}
        result = _expand_config_refs(data)
        self.assertEqual(result["SubAgentModel"], "claude-sonnet-4-5-20250929")

    def test_non_ref_strings_unchanged(self) -> None:
        data = {"Model": "claude-sonnet-4-5-20250929", "Provider": "anthropic"}
        result = _expand_config_refs(data)
        self.assertEqual(result["Provider"], "anthropic")

    def test_non_string_values_unchanged(self) -> None:
        data = {"MaxTokens": 8192, "Model": "claude", "Enabled": True}
        result = _expand_config_refs(data)
        self.assertEqual(result["MaxTokens"], 8192)
        self.assertIs(result["Enabled"], True)

    def test_missing_ref_key_raises(self) -> None:
        data = {"SubAgentModel": "#NonExistentKey"}
        with self.assertRaises(KeyError):
            _expand_config_refs(data)

    def test_multiple_refs_to_same_key(self) -> None:
        data = {
            "Model": "claude-sonnet-4-5-20250929",
            "Stage2Model": "#Model",
            "SubAgentModel": "#Model",
            "ToolResultSummarizationModel": "#Model",
        }
        result = _expand_config_refs(data)
        self.assertEqual(result["Stage2Model"], "claude-sonnet-4-5-20250929")
        self.assertEqual(result["SubAgentModel"], "claude-sonnet-4-5-20250929")
        self.assertEqual(result["ToolResultSummarizationModel"], "claude-sonnet-4-5-20250929")

    def test_ref_with_whitespace_trimmed(self) -> None:
        data = {"Model": "claude", "SubAgentModel": " #Model "}
        result = _expand_config_refs(data)
        self.assertEqual(result["SubAgentModel"], "claude")

    def test_hash_in_middle_of_string_not_treated_as_ref(self) -> None:
        data = {"Description": "Use #Model for details", "Model": "claude"}
        result = _expand_config_refs(data)
        self.assertEqual(result["Description"], "Use #Model for details")


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
