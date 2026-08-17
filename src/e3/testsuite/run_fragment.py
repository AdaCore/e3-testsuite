"""Shallow module to run a test fragment in a separate process.

Doing this in a module separate from `e3.testsuite.fragment` (rather than have
the `if __name__` block in that module directly) is necessary so that entities
from that module are imported rather than belong to the __main__ module.
"""

from e3.testsuite.fragment import run_fragment


# TODO: Investigate why the pytest-cov plugin fails to track coverage in this
# module (it is supposed to handle subprocesses).


if __name__ == "__main__":  # no cover
    run_fragment()
