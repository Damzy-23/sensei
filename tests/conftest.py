"""Test settings. Set before the app is imported, so a developer's .env cannot change
what the tests exercise (python-dotenv does not override variables already set)."""

from __future__ import annotations

import os

os.environ["SENSEI_USE_STUBS"] = "1"  # tests of the real loop switch this off themselves
os.environ["HINT_MODEL"] = "base"
os.environ["ANTHROPIC_API_KEY"] = ""  # no test may reach a real model
os.environ["SENSEI_LOG_FIRESTORE_DB"] = ""  # nor a real Firestore: with either of these set, the real loop
os.environ["SENSEI_STATE_FIRESTORE_DB"] = ""  # would write test sessions and tickets into that database
