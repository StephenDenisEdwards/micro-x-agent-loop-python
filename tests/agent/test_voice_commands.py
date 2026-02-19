import unittest

from micro_x_agent_loop.commands.voice_command import parse_voice_start_options


class VoiceCommandParsingTests(unittest.TestCase):
    def test_parse_start_with_device_name_and_tuning(self) -> None:
        parts = [
            "/voice",
            "start",
            "microphone",
            "--mic-device-name",
            "Headset",
            "Jabra",
            "--chunk-seconds",
            "2",
            "--endpointing-ms",
            "500",
            "--utterance-end-ms",
            "1500",
        ]

        opts, error = parse_voice_start_options(parts, line_prefix="assistant> ")

        self.assertIsNone(error)
        assert opts is not None
        self.assertEqual("microphone", opts.source)
        self.assertEqual("Headset Jabra", opts.mic_device_name)
        self.assertEqual(2, opts.chunk_seconds)
        self.assertEqual(500, opts.endpointing_ms)
        self.assertEqual(1500, opts.utterance_end_ms)

    def test_parse_start_rejects_non_integer_chunk(self) -> None:
        parts = ["/voice", "start", "--chunk-seconds", "x"]

        opts, error = parse_voice_start_options(parts, line_prefix="assistant> ")

        self.assertIsNone(opts)
        assert error is not None
        self.assertIn("chunk-seconds must be an integer", error)


if __name__ == "__main__":
    unittest.main()
