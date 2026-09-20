import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from jev_router.adapters import command_for_prompt, execute_plan
from jev_router.registry import ModelSpec, model_fingerprint


class AdapterTests(unittest.TestCase):
    def test_execute_plan_uses_captain_after_parallel_workers(self):
        models = [
            ModelSpec(id="worker", provider="codex", model="sol", approved=True),
            ModelSpec(id="captain", provider="claude", model="opus", approved=True),
        ]
        checked_at = datetime.now(timezone.utc).isoformat()
        health = {
            model.id: {"ok": True, "checked_at": checked_at, "model_fingerprint": model_fingerprint(model)}
            for model in models
        }
        calls = []

        def runner(command, timeout):
            calls.append(command)
            return 0, "answer", ""

        result = execute_plan(
            {
                "status": "ok",
                "mode": "orchestration",
                "captain_id": "captain",
                "worker_ids": ["captain", "worker"],
            },
            models,
            "task",
            runner=runner,
            health=health,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["model_count"], 2)
        self.assertEqual(len(calls), 2)

    def test_prompt_command_keeps_provider_arguments(self):
        model = ModelSpec(id="sol", provider="codex", model="sol", argv=("-m", "sol"))
        self.assertEqual(command_for_prompt(model, "task")[-2:], ["-m", "sol"])

    def test_option_like_prompt_is_rejected_before_provider_execution(self):
        model = ModelSpec(id="sol", provider="codex", model="sol")
        with self.assertRaises(ValueError):
            command_for_prompt(model, "--unexpected-provider-option")

    def test_execute_plan_rejects_unapproved_model(self):
        model = ModelSpec(id="unapproved", provider="codex", model="sol")
        result = execute_plan(
            {"status": "ok", "mode": "single", "worker_id": "unapproved", "captain_id": "unapproved", "worker_ids": ["unapproved"]},
            [model],
            "task",
            health={"unapproved": {"ok": True, "checked_at": datetime.now(timezone.utc).isoformat()}},
        )
        self.assertFalse(result["ok"])
        self.assertIn("ineligible", str(result["reason"]))

    def test_provider_subprocess_does_not_inherit_router_secrets(self):
        import jev_router.adapters as adapters

        with patch.dict("os.environ", {"TYPESAFE_API_KEY": "secret", "JEV_EVIDENCE_KEY": "evidence"}, clear=False):
            with patch.object(adapters.subprocess, "run", return_value=type("Result", (), {})()) as run:
                adapters._run(["provider"], 1)
        environment = run.call_args.kwargs["env"]
        self.assertNotIn("TYPESAFE_API_KEY", environment)
        self.assertNotIn("JEV_EVIDENCE_KEY", environment)


if __name__ == "__main__":
    unittest.main()
