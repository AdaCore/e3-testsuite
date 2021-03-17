import os

for key, value in sorted(os.environ.items()):
    if key.startswith("E3_TESTSUITE_VAR"):
        print(f"{key}={value}")
