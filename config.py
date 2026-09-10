"""
Loads settings from config.json.

Why this exists: a real product doesn't have file paths buried inside
its code. If someone wanted to point this agent at a different
company's policy, or a different inbox folder, they should be able to
change one settings file — not go hunting through scripts.
"""

import json
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        config = json.load(f)

    # Turn the relative paths in config.json into full paths, so it
    # doesn't matter which folder you run the scripts from.
    config["policy_file"] = os.path.join(PROJECT_ROOT, config["policy_file"])
    config["inbox_dir"] = os.path.join(PROJECT_ROOT, config["inbox_dir"])
    config["log_file"] = os.path.join(PROJECT_ROOT, config["log_file"])
    config["approvals_file"] = os.path.join(PROJECT_ROOT, config.get("approvals_file", "approvals.json"))
    # Where documents uploaded through the dashboard are kept. Deliberately NOT
    # the watched inbox: a file the watcher picks up gets reviewed a second time
    # on its next pass, and one upload should mean one review.
    config["uploads_dir"] = os.path.join(PROJECT_ROOT, config.get("uploads_dir", "uploads"))

    return config
