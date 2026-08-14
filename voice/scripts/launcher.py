"""Entry point for PyInstaller.

PyInstaller is handed a *script*, and a script has no parent package — so aiming
it straight at ``src/mlqvoice/__main__.py`` makes every relative import in the
package fail with "attempted relative import with no known parent package", and
the built exe dies before it draws anything.  Importing the package by name from
outside it is what gives those imports a package to be relative to.
"""

from mlqvoice.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
