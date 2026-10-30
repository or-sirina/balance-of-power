"""
Named save slots, and the portable game file.

The game autosaves one file and can quick-save another, but a nine-turn game is
an evening's entertainment and one slot means starting a new game destroys the
old one.  This dialog lists the slots on disk, with the year and a summary of
each, and can save, load or delete them.

Slots are plain pickle files in the per-user data directory.  That is the same
mechanism the autosave already used, so nothing about the world format changes —
but it does mean a slot is executable content: load only files you saved.

Export and Import are the other half.  A slot belongs to this machine and this
Python; a *game file* (:mod:`Net.GameFile`) is one versioned, checksummed,
compressed document that survives being emailed to a colleague with a different
build — which is also the transport play-by-mail hands around.  They live here
because that is where a player already goes to move a game about, and because a
second dialog saying "choose a file" would be a second place to look.
"""

import os
import time

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QAbstractItemView, QDialog, QFileDialog, QHBoxLayout,
                             QHeaderView, QInputDialog, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout)

import Local
import Paths
import Theme
from Net import GameFile
from Theme import Palette

SAVE_DIR_NAME = "saves"
SUFFIX = ".bop"


def save_dir():
    path = os.path.join(Paths.user_dir(), SAVE_DIR_NAME)
    os.makedirs(path, exist_ok=True)
    return path


#: Longest slot name; a path much past this fails on Windows.
MAX_NAME = 60


def clean_name(name):
    """The slot name that will really be used for what the player typed."""
    safe = "".join(c for c in name if c.isalnum() or c in " -_()").strip()
    return safe[:MAX_NAME].strip() or "save"


def slot_path(name):
    return os.path.join(save_dir(), clean_name(name) + SUFFIX)


def meta_path(name):
    return slot_path(name) + ".json"


def read_meta(name):
    """The little sidecar written next to each slot.

    Reading a year out of the pickle itself would mean unpickling it — slow, and
    it executes whatever the file contains.  A sidecar is both faster and safer,
    and it can carry the score line as well.
    """
    import json
    try:
        with open(meta_path(name), encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_meta(name, world):
    import json
    try:
        with open(meta_path(name), "w", encoding="utf-8") as handle:
            json.dump({
                "year": world.year,
                "level": world.level,
                "twoPlayer": bool(world.twoPFlag),
                "scores": [world.country[0].score - world.country[0].initScore,
                           world.country[1].score - world.country[1].initScore],
                "saved": time.time(),
            }, handle)
    except OSError:
        pass


def delete_meta(name):
    try:
        os.remove(meta_path(name))
    except OSError:
        pass


def list_slots():
    """(name, path, mtime, size) for every slot, newest first."""
    out = []
    for entry in os.listdir(save_dir()):
        if not entry.endswith(SUFFIX):
            continue
        path = os.path.join(save_dir(), entry)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        out.append((entry[:-len(SUFFIX)], path, stat.st_mtime, stat.st_size))
    out.sort(key=lambda item: item[2], reverse=True)
    return out


class SaveSlotsWindow(QDialog):
    """Save, load and delete named games."""

    def __init__(self, parent, mode="both"):
        super().__init__(parent)
        self.parent = parent
        self.mode = mode
        self.setWindowTitle("Saved games")
        self.setModal(True)
        self.setMinimumSize(620, 420)

        root = QVBoxLayout()
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: %s;" % Palette.TEXT_MUTED.name())
        root.addWidget(self.hint)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Name", "Year", "Level", "Score", "Saved"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3, 4):
            self.table.horizontalHeader().setSectionResizeMode(column,
                                                               QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.updateButtons)
        self.table.itemDoubleClicked.connect(lambda _item: self.do_load())
        root.addWidget(self.table, 1)

        row = QHBoxLayout()
        row.addWidget(QLabel("Name"))
        self.nameEdit = QLineEdit()
        self.nameEdit.setPlaceholderText("a name for this game")
        row.addWidget(self.nameEdit, 1)
        root.addLayout(row)

        buttons = QHBoxLayout()
        self.saveButton = QPushButton("Save here")
        self.saveButton.setObjectName("primary")
        self.saveButton.clicked.connect(self.do_save)
        self.loadButton = QPushButton("Load")
        self.loadButton.clicked.connect(self.do_load)
        self.deleteButton = QPushButton("Delete")
        self.deleteButton.setObjectName("danger")
        self.deleteButton.clicked.connect(self.do_delete)
        buttons.addWidget(self.saveButton)
        buttons.addWidget(self.loadButton)

        # Export/Import sit next to Save/Load on purpose: they are the same
        # verbs, one for a file this machine owns and one for a file you send to
        # somebody else.
        self.exportButton = QPushButton("Export\u2026")
        self.exportButton.setToolTip(
            "Write one file you can email to another player.")
        self.exportButton.clicked.connect(self.do_export)
        self.importButton = QPushButton("Import\u2026")
        self.importButton.setToolTip(
            "Open a game file somebody sent you. The game in progress is "
            "replaced.")
        self.importButton.clicked.connect(self.do_import)
        buttons.addWidget(self.exportButton)
        buttons.addWidget(self.importButton)

        buttons.addWidget(self.deleteButton)
        buttons.addStretch(1)
        self.closeButton = QPushButton("Close")
        self.closeButton.clicked.connect(self.close)
        buttons.addWidget(self.closeButton)
        root.addLayout(buttons)

        self.transferLabel = QLabel()
        self.transferLabel.setWordWrap(True)
        self.transferLabel.setStyleSheet("color: %s;" % Palette.TEXT_MUTED.name())
        root.addWidget(self.transferLabel)

        self.setLayout(root)
        self.refresh()

    # -- state --------------------------------------------------------------

    def refresh(self):
        world = getattr(self.parent, "world", None)
        if self.mode == "load":
            self.hint.setText("Choose a saved game to continue.")
        else:
            self.hint.setText(
                "Games are saved in this folder: <code>%s</code>. A slot written "
                "by another player is a program file, so open only slots you "
                "trust. <b>Export</b> writes one file you can email; <b>Import</b> "
                "reads one back."
                % save_dir())
        if not self.nameEdit.text() and world is not None:
            self.nameEdit.setText("Balance of Power %d" % world.year)

        entries = list_slots()
        self.table.setRowCount(0)
        for row, (name, _path, mtime, size) in enumerate(entries):
            self.table.insertRow(row)
            meta = read_meta(name)
            self.table.setItem(row, 0, QTableWidgetItem(name))
            self.table.setItem(row, 1, QTableWidgetItem(self.yearOf(name)))
            self.table.setItem(row, 2, QTableWidgetItem(
                self.levelName(meta.get("level"))))
            scores = meta.get("scores") or []
            self.table.setItem(row, 3, QTableWidgetItem(
                " / ".join("{:+,}".format(int(s)) for s in scores) if scores else "?"))
            self.table.setItem(row, 4, QTableWidgetItem(
                time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))))
        self.table.resizeRowsToContents()
        self.updateButtons()

    def yearOf(self, name):
        year = read_meta(name).get("year")
        return str(year) if year else "?"

    def levelName(self, level):
        try:
            names = Local.strings[Local.WINDOW_NEWGAME]
            from Dialog.NewGameWindow import LEVEL_NAME_INDEX
            return names[LEVEL_NAME_INDEX[int(level) - 1]]
        except (TypeError, ValueError, IndexError, KeyError):
            return "?"

    def selected(self):
        row = self.table.currentRow()
        entries = list_slots()
        if 0 <= row < len(entries):
            return entries[row]
        return None

    def updateButtons(self):
        entry = self.selected()
        self.loadButton.setEnabled(entry is not None)
        self.deleteButton.setEnabled(entry is not None)
        self.saveButton.setEnabled(bool(self.nameEdit.text().strip())
                                   and self.mode != "load")
        if entry is not None:
            self.nameEdit.setText(entry[0])

    # -- actions ------------------------------------------------------------

    def do_save(self):
        name = self.nameEdit.text().strip()
        if not name:
            return
        final = clean_name(name)
        path = slot_path(name)
        # Say what the slot is really called when it differs from what was
        # typed (slashes and other symbols are dropped, long names cut), rather
        # than leaving the player to discover it in the list.
        note = ""
        if final != name:
            reason = []
            if len(name) > MAX_NAME:
                reason.append("names are limited to %d characters" % MAX_NAME)
            if any(not (c.isalnum() or c in " -_()") for c in name):
                reason.append("only letters, digits, spaces and - _ ( ) are allowed")
            if not any(c.isalnum() for c in name):
                reason.append("nothing usable was left, so the default name is used")
            note = "\n\nSaved as \u201c%s\u201d (%s)." % (final, "; ".join(reason) or "name tidied")
        if os.path.exists(path):
            answer = QMessageBox.question(
                self, "Balance of Power",
                "A slot called \u201c%s\u201d already exists. Overwrite it?%s" % (final, note),
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
            if answer != QMessageBox.Yes:
                return
            note = ""       # already said above
        if self.parent.saveWorldTo(path):
            self._years = {}
            self.refresh()
            self.nameEdit.setText(final)
            if note:
                QMessageBox.information(self, "Balance of Power",
                                        "The game was saved." + note)
        else:
            reason = getattr(self.parent, "last_save_error", "") or "unknown error"
            QMessageBox.critical(self, "Balance of Power",
                                 "The game could not be saved to that slot: %s" % reason)

    def do_load(self):
        entry = self.selected()
        if entry is None:
            return
        name, path = entry[0], entry[1]
        answer = QMessageBox.question(
            self, "Balance of Power",
            "Load \u201c%s\u201d? The game in progress will be lost unless you "
            "saved it." % name,
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Yes)
        if answer != QMessageBox.Yes:
            return
        if self.parent.loadWorldFrom(path):
            self.accept()
        else:
            QMessageBox.critical(self, "Balance of Power",
                                 "That slot could not be read. It may be from a "
                                 "different version of the game, or damaged.")

    def do_delete(self):
        entry = self.selected()
        if entry is None:
            return
        name, path = entry[0], entry[1]
        answer = QMessageBox.question(
            self, "Balance of Power", "Delete the slot \u201c%s\u201d?" % name,
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer != QMessageBox.Yes:
            return
        try:
            os.remove(path)
            delete_meta(name)
        except OSError as exc:
            QMessageBox.critical(self, "Balance of Power", "Could not delete: %s" % exc)
        self._years = {}
        self.refresh()

    # -- portable game files ------------------------------------------------

    def do_export(self):
        """Write the current game as one file that can be emailed."""
        from Dialog.GameTransfer import export_to, export_filename, summary
        world = getattr(self.parent, "world", None)
        if world is None:
            QMessageBox.information(self, "Balance of Power",
                                   "There is no game to export yet.")
            return
        suggestion = os.path.join(
            os.path.expanduser("~"),
            export_filename(world, turn=getattr(self.parent, "turn_counter", None)))
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export this game to a file", suggestion,
            "Balance of Power game (*%s)" % GameFile.SUFFIX)
        if not path:
            return
        if not path.endswith(GameFile.SUFFIX):
            path += GameFile.SUFFIX
        name = self.nameEdit.text().strip() or "Balance of Power %d" % world.year
        try:
            header = export_to(self.parent, path, game_name=name,
                               turn=getattr(self.parent, "turn_counter", None))
        except GameFile.GameFileError as exc:
            QMessageBox.critical(self, "Balance of Power", "%s" % exc)
            return
        except Exception as exc:
            QMessageBox.critical(self, "Balance of Power",
                                 "The game could not be exported: %s" % exc)
            return
        document = {"meta": header.get("meta") or {}, "created": header.get("created"),
                    "turn": header.get("turn")}
        self.transferLabel.setText("Exported to <code>%s</code> (%s). Send that one "
                                   "file to your opponent."
                                   % (path, summary(document)))

    def do_import(self):
        """Replace the current position with one from a file."""
        from Dialog.GameTransfer import install, read, summary
        path, _filter = QFileDialog.getOpenFileName(
            self, "Import a game file", os.path.expanduser("~"),
            "Balance of Power game (*%s);;All files (*)" % GameFile.SUFFIX)
        if not path:
            return
        try:
            document = read(path, retries=1)
        except GameFile.VersionMismatch as exc:
            QMessageBox.critical(self, "Balance of Power", "%s" % exc)
            return
        except GameFile.GameFileError as exc:
            QMessageBox.critical(self, "Balance of Power",
                                 "That file could not be read.\n\n%s" % exc)
            return
        except Exception as exc:
            QMessageBox.critical(self, "Balance of Power",
                                 "That file could not be read: %s" % exc)
            return
        answer = QMessageBox.question(
            self, "Balance of Power",
            "Import this game?\n\n%s\n\nThe game in progress will be lost "
            "unless you saved it." % summary(document),
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer != QMessageBox.Yes:
            return
        side = self._ask_import_side(document)
        if side is False:
            return
        try:
            install(self.parent, document, side=side)
        except Exception as exc:
            QMessageBox.critical(self, "Balance of Power",
                                 "The game could not be imported: %s" % exc)
            return
        self.transferLabel.setText("Imported %s." % summary(document))
        self.refresh()
        self.accept()

    def _ask_import_side(self, document):
        """Which superpower does the human take?  ``False`` means "cancelled".

        A position always names who was moving on the machine it came from,
        which is the right answer for a hot-seat game and the wrong one for a
        file that arrived from the opponent — so ask, but only in the case where
        it can matter.
        """
        meta = document.get("meta") or {}
        human = str(meta.get("human") or "")
        if not meta.get("two_player") or human not in ("USA", "USSR"):
            return None
        options = ["USA", "USSR"]
        default = options.index(human)
        choice, ok = QInputDialog.getItem(
            self, "Balance of Power",
            "This is a two-player game.\nWhich side do you play?",
            options, default, False)
        if not ok:
            return False
        return 0 if choice == "USA" else 1
