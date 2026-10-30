from PyQt5.QtWidgets import (QBoxLayout, QDialog, QGroupBox, QLabel, QPushButton,
                             QRadioButton)
from constants import *
import Local
from GameLogic.Globals import *
from Theme import Palette
from GameLogic.PolicyRules import policy_info

def plain(text):
    """Local's value strings say "$35,460 Ms"; the rest of the UI says "million"."""
    return text.replace(" Ms", " million") if isinstance(text, str) else text


class PolicyWindow(QDialog):

    def __init__(self, parent):
        super(PolicyWindow, self).__init__(parent)
        self.parent = parent
        mainLayout = QBoxLayout(QBoxLayout.TopToBottom)
        topLayout = QBoxLayout(QBoxLayout.TopToBottom)
        buttonLayout = QBoxLayout(QBoxLayout.LeftToRight)
        self.policy = QGroupBox()
        self.remain = QLabel()
        #: Concrete numbers for the step currently selected, so the player is not
        #: choosing between six radio buttons labelled "level 3".
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet("color: %s;" % Palette.TEXT.name())
        #: One line saying why nothing above zero can be chosen, when that is so.
        self.limitNote = QLabel()
        self.limitNote.setWordWrap(True)
        self.limitNote.setStyleSheet("color: %s;" % Palette.WARN.name())
        self.limitNote.setVisible(False)
        # Labels are set from the policy tables by setMode() before the dialog can
        # be shown; the old "Radio 0..5" text was scaffolding.
        self.opt = [QRadioButton() for i in range(6)]
        for i in self.opt:
            # A radio button gets the height of its text from the style only if
            # the layout is allowed to give it: the dialog used to be pinned to
            # 250 px tall, which squeezed six rows into 11 px each, so the labels
            # were drawn on top of one another and read as smeared.  The minimum
            # here is the line height plus a little air.
            i.setMinimumHeight(24)
            topLayout.addWidget(i)
            i.toggled.connect(self.updatePreview)
        topLayout.setSpacing(2)
        self.policy.setLayout(topLayout)

        # ``self.accept`` / ``self.cancel`` would shadow QDialog's own methods,
        # which Qt itself may call (for example when Esc closes the dialog).
        self.cancelButton = QPushButton("Cancel")
        self.okButton = QPushButton("OK")
        buttonLayout.addWidget(self.cancelButton)
        buttonLayout.addWidget(self.okButton)
        self.cancelButton.released.connect(self.close)
        self.okButton.released.connect(self.doEnactPolicy)
        mainLayout.addWidget(self.policy)
        mainLayout.addWidget(self.preview)
        mainLayout.addWidget(self.limitNote)
        mainLayout.addWidget(self.remain)
        mainLayout.addLayout(buttonLayout)
        self.setLayout(mainLayout)
        # Size to the content instead of to a fixed box: the step labels are as
        # long as the numbers they name ("$400 million per year in military
        # aid"), and the ceiling note wraps to two lines.
        self.setMinimumWidth(380)
        self.setSizeGripEnabled(False)
        self.setModal(True)

    def setMode(self, action):
        world = self.parent.world
        if not self.parent.can_act():
            return
        actor = world.country[world.human]
        self.target = self.parent.mapView.rightSelection
        if self.target is None:
            return
        self.action = action
        info = policy_info(world, actor, action, self.target)
        oldCtrl, mode, maxVal = info.old, info.mode, info.ceiling
        avlResrc = info.avail or 0
        self.info = info
        # Main.p SetPolicy enables every control from step 0 up to the step
        # already held (so OK on an unchanged dialog is a no-op and the player is
        # never pushed down by a ceiling that fell since), plus everything up to
        # the ceiling; treaty and trade steps below the held one stay disabled.
        allowed = info.steps()
        for i in range(6):
            self.opt[i].setEnabled(i in allowed)
            # Say why a step is out of reach, on the button itself.
            self.opt[i].setToolTip(info.reason_for(i))
        # Say why nothing (or not everything) above the held step can be chosen.
        if info.ceiling < oldCtrl:
            text = ("The limit has dropped below your current step: %s "
                    "You may keep it or lower it, not raise it." % info.reason)
        elif max(allowed) < 5:
            text = info.reason or "No higher step is available."
        else:
            text = ""
        self.limitNote.setText(text)
        self.limitNote.setVisible(bool(text))
        self.opt[oldCtrl].setChecked(True)
        self.previewMode = mode
        self.previewCeiling = maxVal
        # Set strings
        if 1 <= action <= 5:
            self.remain.setText(Local.strings[Local.WINDOW_POLICY][0] + plain(Local.formatValue(avlResrc, action)))
        else: self.remain.setText("")
        self.setWindowTitle(Local.strings[Local.DATA_COUNTRIES + self.target.id][Local.CTRY_NAME] + \
            " - " + Local.strings[Local.LABEL_POLICY][action])
        for i in range(6): self.opt[i].setText(plain(Local.parseValue(mode, i)))
        self.updatePreview()
        # The labels and the wrapping ceiling note are only known now, so the
        # size that fits them is only known now.
        self.adjustSize()
        self.setVisible(True)

    #: ``News.actionToUnitMode`` gives each verb a "unit mode", and
    #: ``Local.parseValue`` maps those 0-5, 16 to a block of six labels in
    #: TAG_POLICY.  The first draft of this preview assumed mode 0 was economic
    #: aid; it is military aid, and mode 2 is the money.
    UNIT_MODE_ECON = 2
    UNIT_MODE_MILITARY = 0
    UNIT_MODE_TROOPS = 1

    @staticmethod
    def money(millions):
        """Render an amount the way a person would say it."""
        if millions >= 1000:
            value = millions / 1000.0
            return "$%s billion" % ("%g" % value)
        return "$%s million" % Local.format(int(millions))

    def updatePreview(self):
        """Say what the selected step means, in money, men and ceilings."""
        mode = getattr(self, "previewMode", None)
        if mode is None:
            return
        step = 0
        for i in range(6):
            if self.opt[i].isChecked():
                step = i
                break

        ceiling = getattr(self, "previewCeiling", None)
        if step == 0:
            headline = "Repeals the policy." if self.opt[0].isEnabled() else "\u2014"
            headline = "<b>%s</b>" % headline
        elif mode == self.UNIT_MODE_ECON:
            headline = "<b>%s per year</b> in economic aid" % self.money(
                econConv(step) * 200)
        elif mode == self.UNIT_MODE_MILITARY:
            headline = "<b>%s per year</b> in %s" % (self.money(
                mAidConv(step) * 20), "aid to insurgents"
                if getattr(self, "action", None) == INSGAID else "military aid")
        elif mode == self.UNIT_MODE_TROOPS:
            headline = "<b>%s troops%s</b>" % (Local.format(intvConv(step) * 1000),
                " for the rebels" if getattr(self, "action", None) == INGSINTV else "")
        else:
            headline = "<b>%s</b>" % plain(Local.parseValue(mode, step))

        text = headline
        info = getattr(self, "info", None)
        if info is not None:
            if step < info.old:
                text += ("<br><span style='color:%s'>OK will lower your current "
                         "step.</span>" % Palette.WARN.name())
            elif step > 0 and step >= info.ceiling and info.ceiling < 5 and info.reason:
                text += ("<br><span style='color:%s'>This is the most you can give "
                         "now: %s</span>" % (Palette.WARN.name(), info.reason))
        self.preview.setText(text)

    def doEnactPolicy(self):
        """Hand the chosen level to the main window, which knows whether the
        change belongs to this machine or has to travel to the host."""
        x = 0
        for i in range(6):
            if self.opt[i].isChecked():
                x = i
                break
        self.setVisible(False)
        # Main.p SetPolicy: nothing happens unless the step changed.
        info = getattr(self, "info", None)
        if info is not None and x == info.old:
            return
        self.parent.request_policy(self.action, self.target.id, x)