"""Tests for voice_command parsing utilities."""

from __future__ import annotations

import unittest

from micro_x_agent_loop.commands.voice_command import (
    VoiceStartOptions,
    parse_voice_command,
    parse_voice_start_options,
)


class ParseVoiceCommandTests(unittest.TestCase):
    def test_basic_split(self) -> None:
        parts = parse_voice_command("/voice start")
        self.assertEqual(["/voice", "start"], parts)

    def test_with_quoted_arg(self) -> None:
        parts = parse_voice_command('/voice start --mic-device-name "My Mic"')
        self.assertIn("My Mic", parts)


class ParseVoiceStartOptionsTests(unittest.TestCase):
    def _parse(self, cmd: str):
        parts = parse_voice_command(cmd)
        return parse_voice_start_options(parts, line_prefix="  ")

    def test_default_source(self) -> None:
        opts, err = self._parse("/voice start")
        self.assertIsNone(err)
        self.assertEqual("microphone", opts.source)

    def test_loopback_source(self) -> None:
        opts, err = self._parse("/voice start loopback")
        self.assertIsNone(err)
        self.assertEqual("loopback", opts.source)

    def test_mic_device_id(self) -> None:
        opts, err = self._parse("/voice start --mic-device-id 5")
        self.assertIsNone(err)
        self.assertEqual("5", opts.mic_device_id)

    def test_mic_device_id_missing_value(self) -> None:
        opts, err = self._parse("/voice start --mic-device-id")
        self.assertIsNone(opts)
        self.assertIn("mic-device-id", err)

    def test_mic_device_name(self) -> None:
        opts, err = self._parse("/voice start --mic-device-name MyMic")
        self.assertIsNone(err)
        self.assertEqual("MyMic", opts.mic_device_name)

    def test_mic_device_name_missing_value(self) -> None:
        opts, err = self._parse("/voice start --mic-device-name")
        self.assertIsNone(opts)
        self.assertIn("mic-device-name", err)

    def test_chunk_seconds(self) -> None:
        opts, err = self._parse("/voice start --chunk-seconds 3")
        self.assertIsNone(err)
        self.assertEqual(3, opts.chunk_seconds)

    def test_chunk_seconds_invalid(self) -> None:
        opts, err = self._parse("/voice start --chunk-seconds notanint")
        self.assertIsNone(opts)
        self.assertIn("chunk-seconds", err)

    def test_chunk_seconds_missing(self) -> None:
        opts, err = self._parse("/voice start --chunk-seconds")
        self.assertIsNone(opts)

    def test_endpointing_ms(self) -> None:
        opts, err = self._parse("/voice start --endpointing-ms 300")
        self.assertIsNone(err)
        self.assertEqual(300, opts.endpointing_ms)

    def test_endpointing_ms_invalid(self) -> None:
        opts, err = self._parse("/voice start --endpointing-ms abc")
        self.assertIsNone(opts)
        self.assertIn("endpointing-ms", err)

    def test_endpointing_ms_missing(self) -> None:
        opts, err = self._parse("/voice start --endpointing-ms")
        self.assertIsNone(opts)

    def test_utterance_end_ms(self) -> None:
        opts, err = self._parse("/voice start --utterance-end-ms 1000")
        self.assertIsNone(err)
        self.assertEqual(1000, opts.utterance_end_ms)

    def test_utterance_end_ms_invalid(self) -> None:
        opts, err = self._parse("/voice start --utterance-end-ms xyz")
        self.assertIsNone(opts)
        self.assertIn("utterance-end-ms", err)

    def test_utterance_end_ms_missing(self) -> None:
        opts, err = self._parse("/voice start --utterance-end-ms")
        self.assertIsNone(opts)

    def test_unknown_flag(self) -> None:
        opts, err = self._parse("/voice start --unknown-flag")
        self.assertIsNone(opts)
        self.assertIn("Usage:", err)

    def test_all_options(self) -> None:
        opts, err = self._parse(
            "/voice start microphone --chunk-seconds 2 --endpointing-ms 200 --utterance-end-ms 500"
        )
        self.assertIsNone(err)
        self.assertEqual("microphone", opts.source)
        self.assertEqual(2, opts.chunk_seconds)
        self.assertEqual(200, opts.endpointing_ms)
        self.assertEqual(500, opts.utterance_end_ms)


if __name__ == "__main__":
    unittest.main()
