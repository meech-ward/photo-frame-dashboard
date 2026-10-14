#!/usr/bin/env python3
"""Offline checks for explicit device selection; never opens USB or a socket."""
import ast
import contextlib
import io
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
UID = "0123456789abcdef"
OTHER_UID = "fedcba9876543210"
PROBES = ("device_probe", "auth_device_probe", "jpeg_device_probe", "photo_storage_probe")


def load_probe(name, expected):
    machine = types.ModuleType("machine")
    machine.unique_id = lambda: bytes.fromhex(UID)
    machine.WDT = Mock(side_effect=AssertionError("device effects must follow target checks"))
    tree = ast.parse((HERE / (name + ".py")).read_text())
    # Each probe runs main at its final statement. Load its unchanged functions
    # first so the test can supply a simulated board before calling real main.
    tree.body.pop()
    namespace = {"__name__": name + "_offline"}
    if expected is not None:
        namespace["HOMEHQ_PROBE_TARGET"] = expected
    with patch.dict(sys.modules, {"machine": machine, "badgeware": types.ModuleType("badgeware")}):
        exec(compile(tree, str(HERE / (name + ".py")), "exec"), namespace)
    return namespace, machine


class ProbeTargetTests(unittest.TestCase):
    def check_refusal(self, target, model="Pimoroni Tufty2350 with RP2350", abi=7942):
        for name in PROBES:
            with self.subTest(probe=name, target=target, model=model, abi=abi):
                probe, machine = load_probe(name, target)
                with patch.object(probe["os"], "uname", return_value=types.SimpleNamespace(machine=model)), \
                     patch.object(sys.implementation, "_mpy", abi, create=True), \
                     contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
                    if name == "photo_storage_probe":
                        probe["main"]()
                    else:
                        probe["main"]({"uid": UID})
                machine.WDT.assert_not_called()

    def test_missing_explicit_target_refuses_before_device_effects(self):
        self.check_refusal(None)

    def test_wrong_explicit_target_refuses_before_device_effects(self):
        self.check_refusal(OTHER_UID)

    def test_selected_non_tufty_refuses_before_device_effects(self):
        self.check_refusal(UID, model="Raspberry Pi Pico 2 W with RP2350")

    def test_selected_tufty_with_wrong_abi_refuses_before_device_effects(self):
        self.check_refusal(UID, abi=0)

    def test_matching_tufty_reaches_installed_payload_or_watchdog(self):
        class AcceptedTarget(Exception):
            pass

        for name in PROBES:
            with self.subTest(probe=name):
                probe, machine = load_probe(name, UID)
                machine.WDT.side_effect = AcceptedTarget
                probe["open"] = Mock(side_effect=AcceptedTarget)
                with patch.object(probe["os"], "uname", return_value=types.SimpleNamespace(machine="Tufty2350")), \
                     patch.object(sys.implementation, "_mpy", 7942, create=True), \
                     patch.object(probe["os"], "ilistdir", side_effect=AcceptedTarget, create=True), \
                     self.assertRaises(AcceptedTarget):
                    if name == "jpeg_device_probe":
                        probe["main"]({"uid": UID})
                    else:
                        probe["gate"]()


if __name__ == "__main__":
    unittest.main()
