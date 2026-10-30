# Balance of Power

**[Описание на русском — README.ru.md](README.ru.md)**

A turn-based simulation of the Cold War, 1982 to 1990. You play one of the two
superpowers; the other is played by the computer or by a second person. There is
no territory to take: you spend money, weapons, troops and treaties on the 78
minor countries, and your score is the sum of their opinion of you, weighted by
what each country is worth. A nuclear war means both sides lose.

![Start screen](screenshots/00-start-screen.png)

## Credits

* **Original game:** Chris Crawford, *Balance of Power* (1985) and
  *Balance of Power: The 1990 Edition* (1988), published by Mindscape. The
  original Pascal sources are public at
  <https://github.com/balance-of-power/bop2-pascal-source>.
* **Python port:** Tomasz Ciborski, 2020 —
  <https://github.com/tomaszcib/Balance-of-Power-Reviewed-Python->.
* **This fork** adds the AI (language-model) opponent, advisors, summits,
  objectives, historical events, LAN and play-by-mail multiplayer, and many
  fixes. It was built with the help of AI coding assistants: **Claude**
  (Anthropic) and **DeepSeek**.

The artwork is the original game's. Advisor photographs are from Wikimedia
Commons (`img/advisors/ATTRIBUTION.md`); the music is CC BY
(`music/ATTRIBUTION.md`).

## Install and run

The game needs Python 3.8–3.14 (64-bit) and PyQt5. No administrator rights are
needed. Download the repository (*Code → Download ZIP*), unpack it, and start
the launcher for your system:

| System | Launcher | Notes |
|---|---|---|
| Windows | `start-windows.bat` (double-click) | Installs PyQt5 for the current user on first run. |
| Windows (venv) | `setup-venv-windows.bat` | Same, but inside a separate virtual environment. |
| Linux | `./start-linux.sh` | Offers to install PyQt5 if it is missing (asks first). |
| macOS | `start-mac.command` (double-click) | Calls `start-linux.sh`. |

Or by hand, on any system:

```bash
python3 -m pip install -r requirements.txt
python3 main.py                     # start screen
python3 main.py --game              # skip the start screen
python3 main.py --host 45454        # host a LAN game
python3 main.py --join 192.168.1.42 # join one
```

Saves go to `%LOCALAPPDATA%\balance-of-power` on Windows and
`~/.local/share/balance-of-power` on Linux and macOS (override with
`BOP_USER_DIR`). The detailed install guide, including troubleshooting and
network setup, is `USTANOVKA-RU.txt` (Russian); the rules are `PRAVILA-RU.md` /
`PRAVILA-RU.pdf`, and the full manual is in the game under *Help → Manual*.

## Ways to play

* **One player** against the computer.
* **Hot-seat**: two players on one machine.
* **LAN**: host or join; games on the local network are found automatically.
  `netcheck.py` checks the network; `relay.py` is a relay server for networks
  that block direct connections.
* **Play by mail**: each turn is one file in a shared folder.

Five difficulty levels: Beginner, Intermediate, Expert, Multipolar and Adaptive.
On Adaptive the opposing superpower is played by a language model through any
OpenAI-compatible API (*AI → AI settings*); without an API key it plays like
Multipolar.

## Screenshots

![Map](screenshots/02-map-relations.png)

| Crisis | Advisors' council |
|---|---|
| ![Crisis](screenshots/06-crisis.png) | ![Council](screenshots/10-council.png) |
