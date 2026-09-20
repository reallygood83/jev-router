import tempfile
import unittest
from pathlib import Path

from jev_router.registry import ModelSpec, load_registry, save_registry


class RegistryStorageTests(unittest.TestCase):
    def test_registry_round_trip_preserves_approval_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            original = [
                ModelSpec(
                    id="codex-sol",
                    provider="codex",
                    model="gpt-5.6-sol",
                    approved=True,
                    argv=("-m", "gpt-5.6-sol"),
                    context_tokens=128000,
                    quality_prior=0.8,
                )
            ]

            save_registry(path, original)
            loaded = load_registry(path)

            self.assertEqual(loaded, original)


if __name__ == "__main__":
    unittest.main()
