"""Dependency-light validation usable at every component boundary."""
import compileall
import sys
import unittest


def main():
    if not compileall.compile_dir("src", quiet=1):
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover("tests"))
    return int(not result.wasSuccessful())


if __name__ == "__main__":
    sys.exit(main())
