#!/usr/bin/env python3
"""
Balance of Power — entry point.

Usage::

    python3 main.py                 # start screen
    python3 main.py --game          # skip the start screen, go straight in
    python3 main.py --host 45454    # host a LAN game immediately
    python3 main.py --join 1.2.3.4  # join one
    python3 main.py --netcheck      # test this PC's network (see --netcheck --help)

Run it from anywhere: all assets are resolved relative to this file.  The start
screen is shown before the game unless ``--game`` or ``BOP_NO_START_MENU=1`` is
set, which is also how the test tools and a kiosk-style launch skip it.
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def launcher_libs():
    """The folder start-windows.bat installs PyQt5 into, if it exists.

    The launcher uses ``pip --target`` into the local (not roaming) profile and
    sets PYTHONPATH only for its own window, so ``py main.py`` or
    ``py netcheck.py`` started by hand would not find PyQt5 without this.  The
    tag must match the one the .bat computes: ``py3<minor>-<64-bit?>``.
    """
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        return None
    tag = "py3%d-%s" % (sys.version_info[1], sys.maxsize > 2 ** 32)
    path = os.path.join(base, "balance-of-power", "libs", tag)
    return path if os.path.isdir(path) else None


_LIBS = launcher_libs()
if _LIBS and _LIBS not in sys.path:
    sys.path.append(_LIBS)


def add_qt_plugin_path():
    """Tell Qt where its plugins are before the QApplication exists.

    Qt 5 on Windows works out its own plugin folder through a lossy 8-bit
    conversion, so when PyQt5 sits under a non-ASCII path (``Рабочий стол``, a
    Cyrillic user name in ``%LOCALAPPDATA%``) it looks in ``C:/users/????...``
    and stops with "Could not find the Qt platform plugin windows".  Python
    has the real path, so hand it over.
    """
    try:
        import PyQt5
        from PyQt5.QtCore import QCoreApplication
    except ImportError:
        return
    for sub in (("Qt5", "plugins"), ("Qt", "plugins")):
        path = os.path.join(os.path.dirname(os.path.abspath(PyQt5.__file__)), *sub)
        if os.path.isdir(path):
            QCoreApplication.addLibraryPath(path)
            return


def build_application(argv):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    add_qt_plugin_path()
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(argv)
    app.setApplicationName("Balance of Power")
    app.setApplicationDisplayName("Balance of Power")
    app.setOrganizationName("Balance of Power")
    # Fusion behaves consistently across platforms and, unlike some native
    # styles, honours the custom palette we apply.
    app.setStyle("Fusion")
    import Theme
    app.setFont(Theme.font(10))
    app.setStyleSheet(Theme.stylesheet())
    return app


def install_excepthook():
    """Log uncaught exceptions instead of letting PyQt5 abort the process.

    PyQt5 (5.5+) calls ``qFatal`` when a slot raises and ``sys.excepthook`` is
    the default one, so a single bad network message or file could close the
    whole game.  Only the real application installs this: the test tools do not
    go through ``main()``, so their failures still surface.
    """
    import time
    import traceback

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        sys.stderr.write(text)
        try:
            import Paths
            with open(Paths.user_file("errors.log"), "a", encoding="utf-8") as log:
                log.write("--- %s ---\n%s" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
        except Exception:
            pass

    sys.excepthook = hook
    return hook


def wants_start_menu(argv):
    """Whether to open with the start screen rather than the game.

    A network game started from the command line goes straight in: the player
    has already said what they want, and making them dismiss a menu first would
    be a step backwards.
    """
    if os.environ.get("BOP_NO_START_MENU"):
        return False
    if "--game" in argv or "--host" in argv or "--join" in argv:
        return False
    return True


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    if "--netcheck" in argv:
        # Plain-text diagnosis, no window: the same as running netcheck.py.
        # Checked before --help so that "--netcheck --help" shows its own help.
        import netcheck
        return netcheck.main(argv[argv.index("--netcheck") + 1:])
    if "--help" in argv[1:] or "-h" in argv[1:]:
        print(__doc__)
        return 0
    if "--host" in argv:
        index = argv.index("--host")
        if index + 1 < len(argv):
            try:
                port = int(argv[index + 1])
                if not 0 <= port <= 65535:
                    raise ValueError
            except ValueError:
                print("error: --host needs a port number from 0 to 65535, got %r"
                      % argv[index + 1], file=sys.stderr)
                return 2
    app = build_application(argv)
    install_excepthook()
    from MainWindow import MainWindow
    window = MainWindow(app)
    import Paths
    warning = Paths.take_warning()
    if warning:
        # Say it once, after the first window is up, without blocking startup.
        from PyQt5.QtCore import Qt, QTimer
        from PyQt5.QtWidgets import QMessageBox

        def show_warning():
            box = QMessageBox(QMessageBox.Warning, "Balance of Power", warning)
            box.setAttribute(Qt.WA_DeleteOnClose)
            box.show()
            window._paths_warning_box = box
        QTimer.singleShot(400, show_warning)

    # Nothing generates music here: the themes are made after the first frame is
    # on screen, which is what keeps startup fast on a machine that has no cache.
    if wants_start_menu(argv):
        # The game window is built but stays hidden: it holds the world, the
        # graphics and every dialog, and the start screen is only a way in to
        # it, so building it once and revealing it later is both simpler and
        # faster than tearing it down and rebuilding it.
        from Dialog.StartWindow import StartWindow
        start = StartWindow(window=window)
        start.refresh()
        start.show()
        window.startWindow = start
    else:
        window.show()
        if not window.restored and "--host" not in argv and "--join" not in argv:
            # No autosave to continue: start a real game rather than leaving the
            # player in the unstarted placeholder world (year 1981, no scores).
            window.start_local_game(window.world.level, False, window.world.human)
        if "--host" in argv:
            index = argv.index("--host")
            port = int(argv[index + 1]) if index + 1 < len(argv) else 0
            window.open_multiplayer(autorun="host", port=port)
        elif "--join" in argv:
            index = argv.index("--join")
            address = argv[index + 1] if index + 1 < len(argv) else "127.0.0.1"
            window.open_multiplayer(autorun="join", address=address)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
