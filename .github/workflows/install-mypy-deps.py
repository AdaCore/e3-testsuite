#! /usr/bin/env python3

# Install mypy and its additional dependencies according to the
# .pre-commit-config.yaml source file.

import subprocess

import yaml


with open(".pre-commit-config.yaml") as f:
    config = yaml.safe_load(f)

deps = []

# Look for the repo corresponding to mypy
for repo in config["repos"]:
    if repo["repo"].endswith("/mirrors-mypy"):

        # Extract the version number for mypy
        version = repo["rev"]
        assert version.startswith("v")
        version = version[1:]
        deps.append(f"mypy=={version}")

        # Look for additional dependencies in all hooks
        for hook in repo["hooks"]:
            deps += hook.get("additional_dependencies", [])

# Install all dependencies found
subprocess.check_call(["pip", "install", "--upgrade"] + deps)
