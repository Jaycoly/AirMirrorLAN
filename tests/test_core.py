from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from airmirror_core import (  # noqa: E402
    ReceiverConfig,
    build_uxplay_command,
    config_dir,
    find_uxplay,
    load_config,
    save_config,
    runtime_environment,
    validate_display_mode,
    validate_fixed_pin,
    validate_receiver_name,
)


class ValidationTests(unittest.TestCase):
    def test_display_mode_is_limited_to_two_supported_values(self) -> None:
        self.assertEqual(validate_display_mode("fit"), "fit")
        self.assertEqual(validate_display_mode("stretch"), "stretch")
        for invalid in ("book", "fill", "invalid"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_display_mode(invalid)

    def test_receiver_name_is_trimmed(self) -> None:
        self.assertEqual(validate_receiver_name("  My PC  "), "My PC")

    def test_empty_receiver_name_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_receiver_name("   ")

    def test_pin_must_have_four_digits(self) -> None:
        self.assertEqual(validate_fixed_pin("0123"), "0123")
        self.assertEqual(validate_fixed_pin(""), "")
        for invalid in ("123", "12345", "12a4"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_fixed_pin(invalid)


class CommandTests(unittest.TestCase):
    def test_default_command_uses_windows_sinks_and_random_pin(self) -> None:
        command = build_uxplay_command(Path(r"C:\runtime\uxplay.exe"), ReceiverConfig(), Path(r"C:\records"))
        self.assertEqual(command[0], r"C:\runtime\uxplay.exe")
        self.assertIn("d3d11videosink", command)
        self.assertIn("wasapisink", command)
        self.assertIn("-pin", command)
        self.assertIn("-h265", command)
        self.assertEqual(command[command.index("-s") + 1], "3840x2160")
        self.assertNotIn("-vc", command)
        self.assertEqual(command[command.index("-vs") + 1], "d3d11videosink")
        self.assertNotIn("-mp4", command)

    def test_stretch_mode_disables_sink_aspect_ratio(self) -> None:
        command = build_uxplay_command(
            Path(r"C:\runtime\uxplay.exe"),
            ReceiverConfig(display_mode="stretch"),
            Path(r"C:\records"),
        )
        sink = command[command.index("-vs") + 1]
        self.assertIn("force-aspect-ratio=false", sink)
        self.assertIn("ALT_ENTER", sink)

    def test_compatibility_mode_omits_hevc_request(self) -> None:
        command = build_uxplay_command(
            Path(r"C:\runtime\uxplay.exe"),
            ReceiverConfig(high_resolution=False),
            Path(r"C:\records"),
        )
        self.assertNotIn("-h265", command)
        self.assertNotIn("-s", command)

    def test_fixed_pin_and_recording_are_forwarded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = ReceiverConfig(fixed_pin="0042", record_sessions=True)
            command = build_uxplay_command(Path("uxplay.exe"), config, Path(temporary))
            self.assertEqual(command[command.index("-pin") + 1], "0042")
            self.assertIn("-mp4", command)
            self.assertTrue(Path(temporary).is_dir())

    def test_runtime_environment_replaces_stale_mdns_address(self) -> None:
        old_value = os.environ.get("UXPLAY_MDNS_IPV4")
        os.environ["UXPLAY_MDNS_IPV4"] = "192.0.2.10"
        try:
            with patch("airmirror_core.preferred_ipv4", return_value="198.51.100.25"):
                environment = runtime_environment(Path(r"C:\runtime\uxplay.exe"))
            self.assertEqual(environment["UXPLAY_MDNS_IPV4"], "198.51.100.25")
        finally:
            if old_value is None:
                os.environ.pop("UXPLAY_MDNS_IPV4", None)
            else:
                os.environ["UXPLAY_MDNS_IPV4"] = old_value

    def test_runtime_environment_removes_stale_address_without_a_route(self) -> None:
        old_value = os.environ.get("UXPLAY_MDNS_IPV4")
        os.environ["UXPLAY_MDNS_IPV4"] = "192.0.2.10"
        try:
            with patch("airmirror_core.preferred_ipv4", return_value=None):
                environment = runtime_environment(Path(r"C:\runtime\uxplay.exe"))
            self.assertNotIn("UXPLAY_MDNS_IPV4", environment)
        finally:
            if old_value is None:
                os.environ.pop("UXPLAY_MDNS_IPV4", None)
            else:
                os.environ["UXPLAY_MDNS_IPV4"] = old_value


class ConfigurationTests(unittest.TestCase):
    def test_config_directory_can_be_overridden(self) -> None:
        old_value = os.environ.get("AIRMIRROR_CONFIG_DIR")
        os.environ["AIRMIRROR_CONFIG_DIR"] = r"C:\temporary\AirMirrorLAN-TestConfig"
        try:
            self.assertEqual(config_dir(), Path(r"C:\temporary\AirMirrorLAN-TestConfig"))
        finally:
            if old_value is None:
                os.environ.pop("AIRMIRROR_CONFIG_DIR", None)
            else:
                os.environ["AIRMIRROR_CONFIG_DIR"] = old_value

    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "config.json"
            expected = ReceiverConfig(
                receiver_name="Living Room",
                require_pin=False,
                record_sessions=True,
                high_resolution=False,
                share_folder=r"C:\Transfer",
                display_mode="stretch",
            )
            save_config(expected, target)
            self.assertEqual(load_config(target), expected)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["receiver_name"], "Living Room")

    def test_runtime_discovery_prefers_app_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            app_dir = Path(temporary)
            bundled = app_dir / "runtime" / "bin" / "uxplay.exe"
            bundled.parent.mkdir(parents=True)
            bundled.touch()
            self.assertEqual(find_uxplay(app_dir), bundled.resolve())


if __name__ == "__main__":
    unittest.main()
