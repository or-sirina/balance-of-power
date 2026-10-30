from PyQt5.QtWidgets import QAction, QActionGroup, QMenu, QMenuBar, QMessageBox
from functools import partial

import Paths
import Local
import Theme
from constants import M_TRADE_OUT, M_TRADE_IN

class Menu(QMenuBar):

	LANG_PATH = Paths.LOCALE_DIR

	def __init__(self, parent):
		super(Menu, self).__init__()
		self.parent = parent
		self.submenu = [QMenu() for i in range(4)]
		self.assistantMenu = QMenu()
		self.intelMenu = QMenu()
		self.intelAction = [QAction() for i in range(6)]
		self.assistantAction = [QAction() for i in range(4)]
		self.mapModeSubmenu = [QMenu() for i in range(5)]
		self.mapResrcSubmenu = [QMenu() for i in range(4)]
		self.fileMenuAction = [QAction() for i in range(6)]
		self.helpMenuAction = [QAction() for i in range(2)]
		self.options = [QAction() for i in range(10)]
		self.languageMenu = QMenu()

		# File menu options
		for i in range(6):
			if i in (3,4,5): self.submenu[0].addSeparator()
			self.submenu[0].addAction(self.fileMenuAction[i])
		self.fileMenuAction[0].triggered.connect(partial(parent.newGameWindow.setVisible, True))
		self.fileMenuAction[1].triggered.connect(parent.open_multiplayer)
		self.fileMenuAction[2].triggered.connect(parent.leave_session)
		self.fileMenuAction[3].triggered.connect(parent.open_save_slots)
		self.fileMenuAction[4].triggered.connect(parent.close)
		self.fileMenuAction[5].triggered.connect(parent.do_undo_turn)

		# Help menu options
		for i in self.helpMenuAction: self.submenu[3].addAction(i)
		self.aboutBox = QMessageBox()
		self.helpMenuAction[0].triggered.connect(parent.open_help)
		self.helpMenuAction[1].triggered.connect(self.aboutBox.exec)

		# Map mode submenus
		for i in self.mapResrcSubmenu:
			self.mapModeSubmenu[3].addMenu(i)
		for i,j in zip(parent.controlPanel.mapModeAction, range(len(parent.controlPanel.mapModeAction))):
			if j in range(22,33,1):
				j -= 22
				self.mapResrcSubmenu[0 if j < 2 else (j+1)//3].addAction(i)
			else:
				if j < 8: toInsert = 0
				elif 8 <= j <= 16: toInsert = 1
				elif 17 <= j <= 21: toInsert = 2
				elif j in (M_TRADE_OUT, M_TRADE_IN): toInsert = 1
				elif 33 <= j <= 34: toInsert = 3
				# The encyclopedia modes are 35..57 and have a submenu of their
				# own.  Sending them to "Resources" as well left the fifth
				# submenu, "Encyclopedia", with no entries at all -- a menu that
				# opens and shows nothing.
				elif 35 <= j <= 57: toInsert = 4
				else: toInsert = 4
				self.mapModeSubmenu[toInsert].addAction(i)
		for i in self.mapModeSubmenu: self.submenu[1].addMenu(i)
		
		# Options menu
		self.submenu[2].addAction(self.options[0])
		self.options[0].setCheckable(True)
		self.submenu[2].addSeparator()
		#for i in self.options[1:4]: self.submenu[2].addAction(i)
		for i in range(1,10,1):
			self.submenu[2].addAction(self.options[i])
			self.options[i].setCheckable(i < 3 or i >= 4)
		self.submenu[2].addSeparator()
		# Volume as five steps rather than a slider: it is a setting nobody
		# changes often, and a submenu costs no dialog.
		self.musicVolumeMenu = QMenu()
		self.musicVolumeAction = {}
		volumeGroup = QActionGroup(self)
		for level in (0, 25, 50, 75, 100):
			action = QAction(self)
			action.setCheckable(True)
			action.setChecked(level == 50)
			volumeGroup.addAction(action)
			self.musicVolumeMenu.addAction(action)
			self.musicVolumeAction[level] = action
			action.triggered.connect(self.doSetMusicVolume)
		self.submenu[2].addMenu(self.musicVolumeMenu)
		self.submenu[2].addSeparator()
		# Intelligence is a setting rather than a country policy, so it lives
		# here instead of in the right-click menu: it applies to every country
		# at once and simply costs money.
		intelGroup = QActionGroup(self)
		for i, action in enumerate(self.intelAction):
			action.setCheckable(True)
			action.setChecked(i == 0)
			intelGroup.addAction(action)
			self.intelMenu.addAction(action)
			action.triggered.connect(partial(self.doSetIntel, i))
		self.submenu[2].addMenu(self.intelMenu)
		self.submenu[2].addSeparator()
		self.submenu[2].addMenu(self.languageMenu)
		self.options[2].triggered.connect(self.doSetTerrainVisible)
		self.options[3].triggered.connect(self.doResetMapPos)
		self.options[1].triggered.connect(self.doResetMapPos)
		self.options[4].triggered.connect(self.doSetMotion)
		self.options[5].triggered.connect(self.doSetRelief)
		self.options[6].triggered.connect(self.doSetSound)
		self.options[7].triggered.connect(self.doSetColourBlind)
		self.options[8].triggered.connect(self.doSetAdvisors)
		self.options[9].triggered.connect(self.doSetMusic)

		# Add all menus to the bar
		for i in self.submenu: self.addMenu(i)

	def buildAssistantMenu(self, parent):
		"""The AI features live in their own menu, added after the classic four."""
		self.assistantAction[0].triggered.connect(parent.open_advisor_chat)
		self.assistantAction[1].triggered.connect(parent.open_llm_settings)
		self.assistantAction[2].triggered.connect(parent.open_opponent_log)
		self.assistantAction[3].triggered.connect(parent.open_objectives)
		for i in range(4):
			self.assistantMenu.addAction(self.assistantAction[i])
		self.assistantMenu.setTitle(Local.strings[Local.MENU][75])
		self.addMenu(self.assistantMenu)

		self.loadLanguages()
		self.setStrings()
		self.updateNetworkActions()

	def updateNetworkActions(self):
		"""Enable/disable the network entries to match the session state."""
		session = getattr(self.parent, "session", None)
		online = session is not None and session.is_online
		self.fileMenuAction[1].setEnabled(not online)
		self.fileMenuAction[2].setEnabled(online)
		self.fileMenuAction[5].setEnabled(self.parent.can_undo_turn())

	def setStrings(self):
		strs = Local.strings[Local.MENU]
		for i in range(4): self.submenu[i].setTitle(strs[i + 54])
		for i in range(4): self.mapResrcSubmenu[i].setTitle(strs[i + 22])
		for i in range(5): self.mapModeSubmenu[i].setTitle(strs[i + 26])
		for i in range(5): self.fileMenuAction[i].setText(strs[i + 58])
		self.fileMenuAction[1].setText(Local.strings[Local.MULTIPLAYER][0] + "\u2026")
		self.fileMenuAction[5].setText(strs[74])
		for i in range(2): self.helpMenuAction[i].setText(strs[i + 63])
		for i in range(4): self.options[i].setText(strs[i + 65])
		self.options[4].setText(strs[78])
		# The graphics switches keep their text in their own group, because the
		# options group has been at its limit since the original strings were
		# numbered.
		extra = Local.strings[Local.GRAPHICS_EXTRA]
		self.options[5].setText(extra[1])
		self.options[5].setToolTip(extra[2])
		self.options[6].setText(extra[3])
		self.options[6].setToolTip(extra[4])
		self.options[7].setText(extra[6])
		self.options[7].setToolTip(extra[7])
		advisor_extra = Local.strings[Local.ADVISOR_EXTRA]
		self.options[8].setText(advisor_extra[0])
		self.options[8].setToolTip(advisor_extra[1])
		music = Local.strings[Local.MUSIC]
		self.options[9].setText(music[0])
		self.options[9].setToolTip(music[1])
		self.musicVolumeMenu.setTitle(music[2])
		for level, action in self.musicVolumeAction.items():
			action.setText("%d%%" % level)
		self.intelMenu.setTitle(strs[79])
		for i in range(6):
			self.intelAction[i].setText(strs[80 + i])
		self.languageMenu.setTitle(strs[69])
		self.assistantAction[0].setText(Local.strings[Local.MENU][76])
		self.assistantAction[1].setText(Local.strings[Local.MENU][77])
		self.assistantAction[2].setText(Local.strings[Local.MENU][86])
		self.assistantAction[3].setText(Local.strings[Local.MENU][87])
		self.assistantMenu.setTitle(Local.strings[Local.MENU][75])
		self.aboutBox.setText(Local.strings[Local.WINDOW_PROGINFO][0])
		self.aboutBox.setWindowTitle(Local.strings[Local.WINDOW_PROGINFO][1])
		self.aboutBox.setIconPixmap(self.parent.graphics.progIcon)

	def loadLanguages(self):
		self.languages = dict.fromkeys(Paths.locale_names())
		for lang in self.languages:
			self.languages[lang] = QAction(lang.split(".")[0].capitalize())
		languageGroup = QActionGroup(self)
		for lang in self.languages.keys():
			i = self.languages[lang]
			i.setCheckable(True)
			languageGroup.addAction(i)
			self.languageMenu.addAction(i)

	def doSetTerrainVisible(self):
		"""Check or uncheck 'show terrain' option"""
		self.parent.saveOptions()
		self.parent.mapView.setMapMode(self.parent.mapView.mapMode)

	def doSetIntel(self, level):
		"""Set how much the human player spends on intelligence."""
		self.intelAction[level].setChecked(True)
		self.parent.setIntelLevel(level)

	def updateIntelActions(self, level):
		level = max(0, min(5, int(level)))
		self.intelAction[level].setChecked(True)

	def doSetMotion(self):
		"""Check or uncheck 'reduce motion'."""
		Theme.set_motion_enabled(not self.options[4].isChecked())
		self.parent.saveOptions()

	def doSetRelief(self):
		"""Check or uncheck relief shading: multiply the fill by the terrain."""
		self.parent.mapView.setReliefEnabled(self.options[5].isChecked())
		self.parent.saveOptions()

	def doSetSound(self):
		"""Check or uncheck the turn, crisis and endgame signals."""
		self.parent.mapView.setSoundEnabled(self.options[6].isChecked())
		self.parent.saveOptions()

	def doSetMusic(self):
		"""Check or uncheck the background music."""
		import Music
		Music.set_enabled(self.options[9].isChecked())
		self.parent.statusBarWidget.refreshMusic()
		self.parent.saveOptions()

	def doSetMusicVolume(self):
		"""Pick a music volume from the submenu."""
		import Music
		for level, action in self.musicVolumeAction.items():
			if action.isChecked():
				Music.set_volume(level)
				break
		self.parent.saveOptions()

	def doSetAdvisors(self):
		"""Check or uncheck the model-backed advisors (E1/E2, and the switch)."""
		from GameLogic.AdvisorChat import set_ai_advisors
		set_ai_advisors(self.options[8].isChecked())
		self.parent.saveOptions()

	def doSetColourBlind(self):
		"""Check or uncheck the colour-safe bloc palette (C6)."""
		self.parent.mapView.setColourBlind(self.options[7].isChecked())
		self.parent.saveOptions()

	def doSetZoomMap(self):
		"""Check or uncheck 'map zooming' option"""
		self.parent.saveOptions()
		self.doResetMapPos()

	def doResetMapPos(self):
		"""Reset the map position to the original scale and translation"""
		self.parent.mapView.resetTransform()
