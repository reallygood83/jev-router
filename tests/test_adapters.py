import unittest

from jev_router.adapters import command_for_prompt, execute_plan
from jev_router.registry import ModelSpec


class AdapterTests(unittest.TestCase):
    def test_execute_plan_uses_captain_after_parallel_workers(self):
        models = [
            ModelSpec(id="worker", provider="codex", model="sol"),
            ModelSpec(id="captain", provider="claude", model="opus"),
        ]
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
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["model_count"], 2)
        self.assertEqual(len(calls), 2)

    def test_prompt_command_keeps_provider_arguments(self):
        model = ModelSpec(id="sol", provider="codex", model="sol", argv=("-m", "sol"))
        self.assertEqual(command_for_prompt(model, "task")[-2:], ["-m", "sol"])


if __name__ == "__main__":
    unittest.main()
