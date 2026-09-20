import unittest
from datetime import datetime, timezone

from jev_router.health import command_for_model, partition_health_targets, probe_model, probe_models
from jev_router.registry import ModelSpec, model_fingerprint


class HealthProbeTests(unittest.TestCase):
    def test_command_mapping_keeps_model_arguments(self):
        model = ModelSpec(id="sol", provider="codex", model="gpt-5.6-sol", kind="codex", argv=("-m", "gpt-5.6-sol"))
        command = command_for_model(model)

        self.assertTrue(command[0].endswith("codex"))
        self.assertEqual(command[1:3], ["exec", "--skip-git-repo-check"])
        self.assertEqual(command[-3:], ["-m", "gpt-5.6-sol", "Reply with exactly: OK"])

    def test_grok_probe_puts_flags_before_prompt(self):
        model = ModelSpec(id="grok", provider="grok", model="grok-4.6", kind="grok", argv=("-m", "grok-4.6"))
        command = command_for_model(model)
        self.assertEqual(command[-2:], ["-p", "Reply with exactly: OK"])
        self.assertLess(command.index("--max-turns"), command.index("-p"))

    def test_empty_probe_output_is_not_healthy(self):
        model = ModelSpec(id="empty", provider="grok", model="grok-4.6", kind="grok")

        result = probe_model(model, runner=lambda *args, **kwargs: (0, "", ""))

        self.assertFalse(result["ok"])
        self.assertIn("empty", str(result["reason"]))

    def test_non_ok_probe_output_is_not_healthy(self):
        model = ModelSpec(id="error", provider="grok", model="grok-4.6", kind="grok")

        result = probe_model(model, runner=lambda *args, **kwargs: (0, "ERROR", ""))

        self.assertFalse(result["ok"])

    def test_wrapped_ok_output_is_healthy(self):
        model = ModelSpec(id="live", provider="grok", model="grok-4.6", kind="grok")

        exact = probe_model(model, runner=lambda *args, **kwargs: (0, "OK\n", ""))
        wrapped = probe_model(model, runner=lambda *args, **kwargs: (0, "Sure, OK", ""))

        self.assertTrue(exact["ok"])
        self.assertTrue(wrapped["ok"])
        self.assertTrue(exact.get("exact_ok"))
        self.assertFalse(wrapped.get("exact_ok"))

    def test_fresh_health_is_skipped_until_refresh(self):
        model = ModelSpec(id="live", provider="codex", model="sol", approved=True)
        record = {
            "ok": True,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "model_fingerprint": model_fingerprint(model),
        }
        fresh, stale = partition_health_targets([model], {"live": record})
        self.assertEqual(list(fresh), ["live"])
        self.assertEqual(stale, [])
        _, refreshed = partition_health_targets([model], {"live": record}, refresh=True)
        self.assertEqual([item.id for item in refreshed], ["live"])

    def test_probe_models_runs_each_target(self):
        models = [
            ModelSpec(id="a", provider="codex", model="sol", approved=True),
            ModelSpec(id="b", provider="claude", model="sonnet", approved=True),
        ]
        seen = []

        def runner(command, timeout):
            seen.append(command[-1])
            return 0, "OK", ""

        results = probe_models(models, runner=runner)
        self.assertEqual(set(results), {"a", "b"})
        self.assertTrue(all(item["ok"] for item in results.values()))
        self.assertEqual(len(seen), 2)


if __name__ == "__main__":
    unittest.main()
