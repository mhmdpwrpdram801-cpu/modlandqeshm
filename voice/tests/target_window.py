"""A real window in a real other process, for the typing tests to aim at.

It has to be a separate process. The whole point of ``inject`` is crossing a
process boundary — ``AttachThreadInput`` is a no-op when the target thread is
your own, so a window built inside the test would prove nothing about the one
call most likely to fail.

Whatever lands in the box is written to the file named on the command line, so
the test can read it without any cross-process window messages of its own.
"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPlainTextEdit

TITLE = "mlqvoice-target"


def main() -> int:
    out = sys.argv[1]
    app = QApplication([])

    box = QPlainTextEdit()
    box.setWindowTitle(TITLE)
    box.resize(520, 220)
    box.show()
    box.raise_()
    box.activateWindow()

    def dump() -> None:
        # Written whole then renamed: the test polls this file, and a partial
        # read would look like the wrong text rather than like an unfinished
        # write — a failure that would send someone hunting a paste bug.
        tmp = f"{out}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(box.toPlainText())
        os.replace(tmp, out)

    box.textChanged.connect(dump)
    dump()  # the file appearing at all is how the test knows the window is up

    # Nothing here is worth a stuck runner; if the test dies, so does this.
    QTimer.singleShot(120_000, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
