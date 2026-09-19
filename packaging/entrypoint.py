"""Entry point for the frozen build.

PyInstaller runs its entry script as ``__main__``, which strips the package
context that ``acql.ui.app`` needs for its relative imports. Importing the
module through its package instead keeps those imports working inside the
bundle.
"""

import sys


def main() -> int:
    from acql.ui.app import main as app_main

    return app_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
