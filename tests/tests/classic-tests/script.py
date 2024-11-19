import os
import sys


crlf = False


def print_line(line):
    sys.stdout.write(line)
    sys.stdout.write("\r\n" if crlf else "\n")


for arg in sys.argv[1:]:
    if arg == "-e":
        sys.exit(1)
    if arg == "-crlf":
        crlf = True
    elif arg == "-cwd":
        print_line(os.getcwd())
    elif arg.startswith("-read="):
        with open(arg[6:], "r"):
            pass
    elif arg.startswith("-p"):
        print_line(arg[2:])
    elif arg.startswith("-b"):
        sys.stdout.buffer.write(b"h\xe9llo")
    elif arg.startswith("-i"):
        sys.stdout.buffer.write("héllo".encode("iso-8859-1"))
    elif arg == "-stdin":
        print("From stdin:", repr(sys.stdin.read()))
    else:
        print("Unknown switch")
        sys.exit(2)
