from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from airlock.providers import builtin_providers, resolve_provider
from airlock.util import scrub_agent_env


class HermesProviderTests(unittest.TestCase):
    def test_builtin_adapter_only_requests_hermes_home(self):
        with mock.patch(
            "airlock.providers.registry.shutil.which",
            side_effect=lambda name: "/usr/bin/hermes" if name == "hermes" else None,
        ):
            providers = builtin_providers()
        self.assertEqual(providers["hermes"]["command"], ["hermes", "-z", "{prompt}"])
        self.assertEqual(providers["hermes"]["pass_env"], ["HERMES_HOME"])

    def test_ambient_model_keys_and_repo_authority_are_not_forwarded(self):
        provider = {"command": ["hermes", "-z", "{prompt}"], "pass_env": ["HERMES_HOME"]}
        home = Path(tempfile.mkdtemp(prefix="airlock-hermes-env-"))
        with mock.patch.dict(
            os.environ,
            {
                "HERMES_HOME": "/principal/hermes",
                "OPENROUTER_API_KEY": "openrouter-secret",
                "ANTHROPIC_API_KEY": "anthropic-secret",
                "OPENAI_API_KEY": "openai-secret",
                "GITHUB_TOKEN": "repo-write-secret",
                "GH_TOKEN": "gh-secret",
            },
            clear=True,
        ):
            env = scrub_agent_env(provider["pass_env"], home=home, extra={})
        self.assertEqual(env["HERMES_HOME"], "/principal/hermes")
        self.assertNotEqual(env["HOME"], env["HERMES_HOME"])
        self.assertNotIn("OPENROUTER_API_KEY", env)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn("GH_TOKEN", env)
        self.assertEqual(env["AIRLOCK_RELEASE_AUTHORITY"], "ABSENT")
        self.assertEqual(env["GIT_CONFIG_VALUE_0"], "disabled://airlock-agent-no-push")

    def test_one_explicit_provider_credential_is_allowed(self):
        config = {
            "providers": {
                "hermes": {
                    "command": ["hermes", "-z", "{prompt}"],
                    "pass_env": ["HERMES_HOME", "OPENROUTER_API_KEY"],
                }
            }
        }
        provider = resolve_provider(config, "hermes")
        self.assertEqual(provider["pass_env"], ["HERMES_HOME", "OPENROUTER_API_KEY"])
        home = Path(tempfile.mkdtemp(prefix="airlock-hermes-key-"))
        with mock.patch.dict(
            os.environ,
            {
                "HERMES_HOME": "/principal/hermes",
                "OPENROUTER_API_KEY": "chosen-secret",
                "ANTHROPIC_API_KEY": "unchosen-secret",
                "GITHUB_TOKEN": "repo-write-secret",
            },
            clear=True,
        ):
            env = scrub_agent_env(provider["pass_env"], home=home, extra={})
        self.assertEqual(env["OPENROUTER_API_KEY"], "chosen-secret")
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("GITHUB_TOKEN", env)

    def test_search004_non_secret_controller_context_is_allowed(self):
        config = {
            "providers": {
                "hermes": {
                    "command": ["python", ".airlock/search-004/worker.py", "{prompt}"],
                    "pass_env": [
                        "HERMES_HOME",
                        "SEARCH004_USAGE_FILE",
                        "HERMES_COMMIT",
                        "HERMES_VERSION",
                    ],
                }
            }
        }
        provider = resolve_provider(config, "hermes")
        self.assertEqual(provider["pass_env"], config["providers"]["hermes"]["pass_env"])

    def test_credential_buffet_fails_closed(self):
        config = {
            "providers": {
                "hermes": {
                    "command": ["hermes", "-z", "{prompt}"],
                    "pass_env": ["HERMES_HOME", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"],
                }
            }
        }
        with self.assertRaisesRegex(ValueError, "at most one explicitly named provider credential"):
            resolve_provider(config, "hermes")

    def test_invalid_pass_env_shape_fails_closed(self):
        config = {
            "providers": {
                "hermes": {
                    "command": ["hermes", "-z", "{prompt}"],
                    "pass_env": "OPENROUTER_API_KEY",
                }
            }
        }
        with self.assertRaisesRegex(ValueError, "must be a list"):
            resolve_provider(config, "hermes")


if __name__ == "__main__":
    unittest.main()
