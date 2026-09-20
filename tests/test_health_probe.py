import unittest

from jev_router.health import command_for_model, probe_model
from jev_router.registry import ModelSpec


class HealthProbeTests(unittest.TestCase):
    def test_command_mapping_keeps_model_arguments(self):
        model = ModelSpec(id="sol", provider="codex", model="gpt-5.6-sol", kind="codex", argv=("-m", "gpt-5.6-sol"))
        command = command_for_model(model)

        self.assertTrue(command[0].endswith("codex"))
        self.assertEqual(command[1:4], ["exec", "--skip-git-repo-check", "Reply with exactly: OK"])
        self.assertEqual(command[-2:], ["-m", "gpt-5.6-sol"])

    def test_empty_probe_output_is_not_healthy(self):
        model = ModelSpec(id="empty", provider="grok", model="grok-4.6", kind="grok")

        result = probe_model(model, runner=lambda *args, **kwargs: (0, "", ""))

        self.assertFalse(result["ok"])
        self.assertIn("empty", str(result["reason"]))

    def test_non_ok_probe_output_is_not_healthy(self):
        model = ModelSpec(id="error", provider="grok", model="grok-4.6", kind="grok")

        result = probe_model(model, runner=lambda *args, **kwargs: (0, "ERROR", ""))

        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
