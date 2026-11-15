"""Test settings. Set before the app is imported, so a developer's .env cannot change
what the tests exercise (python-dotenv does not override variables already set)."""

from __future__ import annotations

import os

os.environ["SENSEI_USE_STUBS"] = "1"  # tests of the real loop switch this off themselves
os.environ["HINT_MODEL"] = "base"
os.environ["ANTHROPIC_API_KEY"] = ""  # no test may reach a real model
os.environ["SENSEI_SCOPE_DATA"] = ""  # tests of who-sees-what switch it on themselves
