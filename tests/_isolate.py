"""
Keep a test run away from the developer's real settings, key and network.

Import this FIRST in a test entry point, before anything from the game::

    import _isolate  # noqa: F401  (must come first)

Importing it, in place:

* removes every model credential from the environment (``BOP_LLM_*`` and
  all supported provider API-key variables), so a test can never spend a real key, and so
  ``LLMConfig()`` behaves the same on every machine;
* removes proxy and CA-bundle variables, and sets ``NO_PROXY`` to the loopback
  addresses, so the stub servers the tests start on 127.0.0.1 are reached
  directly and nothing is sent anywhere else;
* points ``BOP_USER_DIR`` at a fresh temporary directory, removed at exit, so
  ``llm.json``, saves and scores from earlier runs (or from the developer's own
  games) cannot leak in.  Set ``BOP_TEST_KEEP_USER_DIR=1`` to keep whatever
  ``BOP_USER_DIR`` is already set to, for debugging a test against a given state.

``scrub(env)`` does the same to a copy of the environment, for tests that start
child processes.
"""

import atexit
import os
import shutil
import tempfile

#: Variables that would carry a credential or redirect traffic.
_DROP_EXACT = ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY",
               "ANTHROPIC_API_KEY", "DASHSCOPE_API_KEY", "GEMINI_API_KEY",
               "GOOGLE_API_KEY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
               "http_proxy", "https_proxy", "all_proxy", "REQUESTS_CA_BUNDLE",
               "SSL_CERT_FILE", "CURL_CA_BUNDLE")


def scrub(env):
    """Remove keys, proxies and CA bundles from ``env`` (a dict) and return it."""
    for name in list(env):
        if name.startswith("BOP_LLM_") or name in _DROP_EXACT:
            del env[name]
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["no_proxy"] = "127.0.0.1,localhost"
    return env


def _fresh_user_dir(env):
    if env.get("BOP_TEST_KEEP_USER_DIR") == "1":
        return
    path = tempfile.mkdtemp(prefix="bop_test_")
    env["BOP_USER_DIR"] = path
    atexit.register(shutil.rmtree, path, True)


scrub(os.environ)
_fresh_user_dir(os.environ)
