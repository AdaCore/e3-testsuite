import logging
import os
import sys

import yaml
from e3.main import Main
from e3.os.process import Run


def main():
    """Run e3-test script."""
    m = Main()

    # Ignore arguments here as they are arguments for the actual testsuite
    m.parse_args(known_args_only=True)

    # Find first the tool configuration file. Keep track of current directory
    # that will be used to select the test subset automatically.
    cwd = os.path.abspath(os.getcwd())
    root_dir = cwd
    while not os.path.isfile(os.path.join(root_dir, "e3-test.yaml")):
        new_root_dir = os.path.dirname(root_dir)
        if new_root_dir == root_dir:
            logging.error("cannot find e3-test.yaml")
            return 1
        root_dir = new_root_dir
    config_file = os.path.join(root_dir, "e3-test.yaml")

    with open(config_file, "rb") as fd:
        config = yaml.load(fd)

    if "main" not in config:
        logging.error("cannot find testsuite main")
        return 1
    p = Run(
        [
            sys.executable,
            os.path.join(root_dir, config["main"]),
            os.path.relpath(cwd, root_dir) + "/",
        ] + config.get("default_args", []),
        output=None,
        cwd=root_dir,
    )
    return p.status
