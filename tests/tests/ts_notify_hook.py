import os.path
import shlex
import sys

from e3.testsuite.result import TestResult


def append_notif(filename, args):
    if args[0] == "--result":
        result = TestResult.load(args[2])
        args[2] = result.test_name
        args.append(result.status.name)

    with open(filename, "a") as f:
        print(shlex.join(args), file=f)


def create_notify_callback(testsuite):
    notifs_filename = os.path.join(
        testsuite.env.output_dir, "notifs_python.txt"
    )

    def notify(notification):
        append_notif(notifs_filename, notification.to_args())

    return notify


def invalid_cb_creator():
    pass


def create_crashing_callback(testsuite):
    def notify(notification):
        raise RuntimeError

    return notify


if __name__ == "__main__":
    if sys.argv[1] == "--crash":
        sys.exit(1)
    append_notif(sys.argv[1], sys.argv[2:])
