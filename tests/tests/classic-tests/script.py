import os
import sys

for arg in sys.argv[1:]:
    if arg == "-e":
        sys.exit(1)
    elif arg == "-cwd":
        print(os.getcwd())
    elif arg.startswith("-read="):
        with open(arg[6:], "r"):
            pass
    elif arg.startswith("-p"):
        print(arg[2:])
    elif arg.startswith("-b"):
        sys.stdout.buffer.write(b"h\xe9llo")
