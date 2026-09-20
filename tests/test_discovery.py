import unittest
from pathlib import Path
from unittest.mock import patch

from jev_router.discovery import _claude_specs, parse_codex_catalog, parse_cursor_models, parse_grok_models


class DiscoveryTests(unittest.TestCase):
    def test_provider_parsers_keep_real_models_and_ignore_headers(self):
        grok = parse_grok_models("Available models:\n- grok-4.6\n- grok-4.5\n")
        cursor = parse_cursor_models("Available models\ncomposer-2.5 - fast\nnot-a-model\n")
        codex = parse_codex_catalog({"models": [{"slug": "gpt-5.6-sol"}, {"slug": ""}, {}]})

        self.assertEqual(grok, ["grok-4.6", "grok-4.5"])
        self.assertEqual(cursor, ["composer-2.5"])
        self.assertEqual(codex, ["gpt-5.6-sol"])

    def test_missing_provider_inventory_is_not_fabricated(self):
        self.assertEqual(parse_grok_models("command failed"), [])
        self.assertEqual(parse_codex_catalog({}), [])

    def test_claude_aliases_are_not_available_without_executable(self):
        with patch("jev_router.discovery.shutil.which", return_value=None):
            specs, status, _source = _claude_specs(Path("/tmp/jev-router-empty-home"))
        self.assertEqual(specs, [])
        self.assertEqual(status, "unavailable")


if __name__ == "__main__":
    unittest.main()
