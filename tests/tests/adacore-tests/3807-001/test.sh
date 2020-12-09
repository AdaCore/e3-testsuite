# Try creating two files, "-o" and "test.exe"
# This used to trick the AdaCoreTestDriver into replacing "-o test.exe" with
# "-o test", which made "ls test.exe" fail.
touch -- -o test.exe
ls test.exe
