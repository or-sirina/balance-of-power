"""
The rules, in the game.

The original shipped with a printed manual and the port inherited the habit of
not explaining itself: the Help menu had a disabled "Instructions" entry, the
scoring formula appeared nowhere, and a new player had no way to find out what
DEFCON 2 costs or why the option they wanted was greyed out.

Written to be read once.  Every number here is the number the code uses.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton,
                             QTabWidget, QTextBrowser, QVBoxLayout)

from Theme import Palette

from constants import GAME_BASE_YEAR, GAME_END_YEAR, GAME_START_YEAR

CSS = """
h3 { color: #e0a33c; margin-bottom: 2px; }
b  { color: #e2e9f2; }
code { color: #9fd0a0; }
table { border-collapse: collapse; }
td, th { padding: 2px 10px 2px 0; }
th { color: #93a6bd; text-align: left; }
/* Qt paints an anchor in the colour the *document* gives it, and its default
   is a dark blue that all but disappears on this background.  The palette's
   Link role is not consulted, so the rule has to be here. */
a, a:visited { color: %s; }
""" % Palette.LINK.name()

GOAL = """
<h3>The goal</h3>
<p>You play one of the two superpowers from {base} to {end}. Your score is the
<b>increase</b> in your geopolitical prestige over those years. It is not your
total, and it is not territory.</p>
<p>Prestige is:</p>
<p><code>score = \u03a3 over the 78 minor countries of
(their opinion of you \u00d7 that country's prestige value) \u00f7 1024</code></p>
<p>The two superpowers are not counted, and neither is the other side's opinion
of you.</p>
<p>The bonuses from the live <b>Objectives</b> are added to this score.</p>
<p>A country's <b>prestige value</b> comes from its military spending and its
military manpower together: a rich micro-state and a huge poor one are both
worth little. The <i>Prestige value</i> map mode shows what each country is
worth.</p>
<p>Opinion rises when you help a government and falls when you attack one.</p>
<p>The game ends in {end} and the higher score wins. A nuclear war voids
everything: nobody wins it.</p>
"""

CREDITS = """
<h3>Who made this</h3>
<table>
<tr><th>Original design</th><td><b>Chris Crawford</b>, 1985 and 1988, published
by Mindscape. The 1990 Edition is the version this one follows.</td></tr>
<tr><th>Python port</th><td><b>Tomasz Ciborski</b>, 2020: a Python and PyQt5
adaptation of the original Pascal sources.</td></tr>
<tr><th>Fork author</th><td><b>Vasilii Vinogradov</b>: the model opponent, the
advisors, summits, the intermediate objectives and network play.</td></tr>
</table>
<h3>Thanks</h3>
<p>The original Pascal sources are public
(<a href="https://github.com/balance-of-power/bop2-pascal-source">bop2-pascal-source</a>)
and were used to check the rules. The artwork is the original's. The advisor
photographs come from Wikimedia Commons and are credited in
<code>img/advisors/ATTRIBUTION.md</code>.</p>
"""


POLICIES = """
<h3>The nine policies</h3>
<table>
<tr><th>Policy</th><th>What it does</th></tr>
<tr><td><b>Military aid</b></td><td>Strengthens the government. The goodwill you
gain depends on how much the recipient needs the help.</td></tr>
<tr><td><b>Aid to insurgents</b></td><td>Strengthens the rebels. Very provocative
for what it costs.</td></tr>
<tr><td><b>Intervene for government</b></td><td>Your troops fight for the
government. Raises the chance of meeting Soviet troops, and of a crisis going
nuclear.</td></tr>
<tr><td><b>Intervene for rebels</b></td><td>Your troops fight for the rebels. The
most provocative thing you can do.</td></tr>
<tr><td><b>Economic aid</b></td><td>Money straight out of your GNP into theirs.
Lowers the chance of a coup, and does much more in a poor country than in a rich
one.</td></tr>
<tr><td><b>Destabilization</b></td><td>Covert action to provoke a coup. One-shot: it
lapses each year.</td></tr>
<tr><td><b>Diplomatic pressure</b></td><td>Intimidation. Pushes a country towards
Finlandization and forces it to spend more on its army. One-shot.</td></tr>
<tr><td><b>Treaty</b></td><td>A graded commitment: the higher the step, the more
you owe the client. You cannot lower it yourself; the client can, and losing one
weakens every other treaty you hold.</td></tr>
<tr><td><b>Trade</b></td><td>Purely a diplomatic statement, with no economic
effect. Multipolar level and above only.</td></tr>
</table>

<h3>Steps</h3>
<p>Every policy has six steps, 0 (none) to 5 (maximum). Sending 0 repeals it.
Aid and intervention are annual commitments that persist until you change
them.</p>
<table>
<tr><th>Step</th><th>Economic aid</th><th>Military / insurgent aid</th><th>Troops</th></tr>
<tr><td>0</td><td>\u2014</td><td>\u2014</td><td>\u2014</td></tr>
<tr><td>1</td><td>$0.2 bn</td><td>$20 m</td><td>1,000</td></tr>
<tr><td>2</td><td>$0.4 bn</td><td>$100 m</td><td>5,000</td></tr>
<tr><td>3</td><td>$1 bn</td><td>$400 m</td><td>20,000</td></tr>
<tr><td>4</td><td>$2 bn</td><td>$1 bn</td><td>100,000</td></tr>
<tr><td>5</td><td>$4 bn</td><td>$2 bn</td><td>500,000</td></tr>
</table>

<h3>Why an option is greyed out</h3>
<p>Four things can stop you:</p>
<p><b>Diplomatic</b>: a country will not accept generosity from a power it
distrusts. Improve the relationship first.</p>
<p><b>Budgetary</b>: you cannot give away more than you have. Aid comes out of
military spending and men out of your army, and both are shared across every
country you are helping. What you spend on intelligence is not available for
aid.</p>
<p><b>Staging areas</b>: aid to insurgents and intervention for rebels need
troops supporting a government in a <i>contiguous</i> country. The highest step
you may send is one above the highest step of troops you already have next door.
With no staging area at all you may still send step 1 of weapons, and step 2 of
troops.</p>
<p><b>The balance on the ground</b>: you cannot arm a rebellion that is already
being beaten. The stronger the government is against the insurgents, the lower
the step you may send.</p>
"""

CRISES = """
<h3>How a crisis starts</h3>
<p>When you do something the other superpower objects to, it may contest the
move. How much it cares depends on its relationship with the country, its treaty,
whose sphere the country is in, and how adventurous it is feeling.</p>

<h3>The ladder</h3>
<p>A crisis has nine rungs, numbered 9 (the safest) down to 1. Each side in turn
either <b>backs down</b> or <b>pushes on</b>. Every push takes the crisis one rung
further, and every rung makes backing down cost more.</p>
<table>
<tr><th>Rung</th><th>Where you are</th></tr>
<tr><td>9-7</td><td>Back channel. Backing down here costs little.</td></tr>
<tr><td>6-5</td><td>Diplomatic crisis. It is public, and prestige is on the
table.</td></tr>
<tr><td>4-2</td><td>DEFCON 4, 3 and 2. <b>The risk of an accidental launch
starts at rung 4.</b> It is zero while relations are friendly and grows as they
sour.</td></tr>
<tr><td>1</td><td>DEFCON 1. Nuclear war. You lose, whatever your score.</td></tr>
</table>
<p>Backing down is <b>free on rungs 9 and 8</b>. From rung 7 down the side that
backs down loses prestige in proportion to how far the crisis had climbed, and
<b>every</b> minor country's opinion shifts towards the winner, not just the
country in dispute. After a big move (a large intervention, say) one retreat can
cost thousands of points, more than any number of aid moves earn, and leave
countries refusing your aid for the rest of the game. Read <b>Prestige at
risk</b> in the crisis window before you give way. The same holds in a
two-player game.</p>
<p>In the news list, the <b>Action possible?</b> column means &ldquo;you can
contest this move&rdquo;.</p>
<p>If the side that made the move is the one to give way, the move is undone:
the aid is withdrawn, the troops come home. If the challenger gives way, the
move stands.</p>
<p>In a two-player game, each side may propose a summit once per crisis, from
the escalation phase. Proposing is the proposer's yes and the other side answers:
a yes keeps the move standing, takes the crisis down a rung and ends it,
costing nobody any face, and a refusal
costs the refuser credibility and hands the decision back to the proposer.</p>
<p>The four advisors weigh different things (relations, treaties, influence and
resolve), so they often disagree.</p>
"""

LEVELS = """
<h3>The five difficulties</h3>
<table>
<tr><th>Level</th><th>What it changes</th></tr>
<tr><td><b>Beginner</b></td><td>Military aid, aid to insurgents and both
interventions. The world is fairly predictable.</td></tr>
<tr><td><b>Intermediate</b></td><td>Adds economic aid and destabilization. Coups are
modelled.</td></tr>
<tr><td><b>Expert</b></td><td>Adds treaties and diplomatic pressure.
Finlandization is modelled.</td></tr>
<tr><td><b>Multipolar</b></td><td>Adds trade. All 78 minor countries run their own
foreign policy and can go to war with each other \u2014 which drags the
superpowers in.</td></tr>
<tr><td><b>Adaptive (LLM)</b></td><td>Multipolar rules, but the opposing
superpower is planned by a language model. Needs an API key; without one it
plays exactly like Multipolar and the status bar says so.</td></tr>
</table>
<p>Higher levels also randomise the starting world more, so the same country is
not always in the same hands.</p>

<h3>Intelligence</h3>
<p>You never see the true level of world tension. You see an <i>estimate</i>,
and it can be wrong by about a quarter of the scale. Buying intelligence narrows
that error, and costs the same money you would otherwise spend on aid.</p>

<h3>Playing</h3>
<table>
<tr><td>Select a country</td><td>Left click it on the map</td></tr>
<tr><td>Enact a policy</td><td>Right click the country and pick the policy from the menu</td></tr>
<tr><td>Country detail</td><td>Double click it</td></tr>
<tr><td>Zoom and pan</td><td>Mouse wheel; middle-drag</td></tr>
<tr><td>End the turn</td><td>The button in the Year panel</td></tr>
<tr><td>Two players, one computer</td><td>Both move in the same year. The first presses <i>Pass to ...</i>, the second presses <i>End the year</i>. <i>Switch player</i> swaps the mouse without ending anything.</td></tr>
<tr><td>Undo last turn</td><td>File menu. Single-machine games, once per turn.</td></tr>
<tr><td>Saved games</td><td>File \u2192 Save game. Games are saved in named slots.</td></tr>
</table>
<p><i>File \u2192 Multiplayer</i> hosts or joins a game on the local network.
The host's machine holds the game. If the list stays empty, type the host's
address in the box.</p>
"""


class HelpWindow(QDialog):
    """The manual, as tabs."""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("Manual")
        self.setModal(False)
        self.setMinimumSize(640, 440)
        self.resize(760, 620)

        root = QVBoxLayout()
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        self.tabs = QTabWidget()
        sections = (
            ("Goal and score", GOAL.format(start=GAME_START_YEAR, base=GAME_BASE_YEAR,
                                           end=GAME_END_YEAR)),
            ("Policies", POLICIES),
            ("Crises", CRISES),
            ("Levels and controls", LEVELS),
            ("Credits", CREDITS),
        )
        for title, body in sections:
            view = QTextBrowser()
            view.setOpenExternalLinks(True)
            view.setHtml("<style>%s</style>%s" % (CSS, body))
            self.tabs.addTab(view, title)
        root.addWidget(self.tabs, 1)

        buttons = QHBoxLayout()
        self.advisorsButton = QPushButton("Ask an advisor\u2026")
        self.advisorsButton.clicked.connect(self.open_advisors)
        self.closeButton = QPushButton("Close")
        self.closeButton.clicked.connect(self.close)
        buttons.addWidget(self.advisorsButton)
        buttons.addStretch(1)
        buttons.addWidget(self.closeButton)
        root.addLayout(buttons)
        self.setLayout(root)

    def open_advisors(self):
        self.parent.open_advisor_chat()
