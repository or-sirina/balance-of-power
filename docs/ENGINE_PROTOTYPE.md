# Godot engine prototype

This playable desktop prototype presents the existing Python rules in Godot 4.7.2. Godot handles the map, controls, animation, sound and localization; Python remains authoritative for policy, crises, yearly simulation and model calls. Keeping the established rules avoids a second simulation drifting from the original. The tradeoff is packaging both runtimes.

Godot is open source under the [MIT license](https://godotengine.org/license/). See the [native packaging instructions](../packaging/godot/NATIVE-BUILDS.md) for build requirements and validation.

## Standalone Linux build

The generated `dist-godot/BalanceOfPower-linux.tar.gz` contains the exported game, frozen Python launcher, required runtime files and credits. Extract it and run `linux/BalanceOfPower --language ru`. Keep the executable, `bop-game`, its `.pck`, `_internal` and `credits` together. It does not require separately installed Python or Godot.

Linux packages require compatible system libraries. For reproducible native builds, see [packaging instructions](../packaging/godot/NATIVE-BUILDS.md). Export success alone does not establish platform compatibility.

## Running from source

Install Godot 4.7.2 and Python 3. The Godot frontend and its Python backend use the standard library at runtime; PyQt5 is needed for the original Qt application and some asset regeneration workflows, not for the source launcher. The launcher finds `godot` or `godot4` on PATH, the standard macOS app location, or the project's local Linux tool installation. Specify a different executable with `--godot /absolute/path/to/godot` or `BOP_GODOT`.

```sh
python3 tools/run_godot.py --language ru
# Linux: packaging/run-godot.sh --language en
# macOS: packaging/run-godot.command --language ru
```

On Windows, run `packaging\run-godot.bat --language ru` from a command prompt; `py -3` and Godot must be available, or set `BOP_GODOT` to the executable. The launcher imports project assets with a headless editor process before starting the game, so a source checkout does not need a pre-existing `godot/.godot` cache. Godot closes when the game exits; the launcher also shuts down the local bridge.

Use `--language en` or `--language ru` to select a presentation language. The start menu offers Continue, New, Load, Learn, Multiplayer, Settings, Help, Credits and Quit. The large map has country, news and tutorial overlays and all 60 original map modes with difficulty restrictions. Reports include scores, objectives, intelligence, opponent history and undo. Named saves support deletion and `.bopg` import/export; undo is available once per turn, including hotseat. The interface also includes policy controls, crises, advisors, AI settings, a guided tutorial and a full English/Russian manual. Presentation options include a colorblind palette, relief, original synthesized cues and music controls.

Multiplayer supports LAN hosting and joining, discovery, chat and reconnection, a teacher byte-forwarding relay, hotseat, and play-by-mail via a shared folder. Godot networking uses `engine-bridge-v1` over BOP1 framing and does not crossplay directly with older Qt clients. The Qt application remains available.

The [interactive map prototype](LIVING_MAP.md) adds original 3D city miniatures with streets and trees, stronger terrain relief, conflict/unrest scenes, clickable event briefings and aid/trade links. The Layers menu keeps these overlays optional. Wheel or +/− zoom, double-click focuses a country, and F restores the world view. Country positions remain schematic until the geographic map is replaced.

**Dispatches / Донесения** opens an interactive briefing over the map. Search the full current news feed, filter policy moves, world events or moves that can be challenged, and select a story to see its country outline, full report, policy values and context. **Show on map** focuses the related country; **Country details** opens its report. Eligible stories retain the existing crisis challenge action. The feed follows the simulation’s importance order, rather than inventing publication times, and preserves the selected story through ordinary updates. Generated reports have no individual timestamps; known historical events show their recorded year.

## Architecture and settings

`EngineBridge` hosts the Python engine in the launcher process. Godot sends JSON commands to a loopback HTTP server (`POST /command`) with a per-launch bearer token. The server returns game state and command results; the Python engine remains responsible for game rules and save data. The launcher stops the server and game together. This local protocol is an implementation interface, not a public remote service. The Python core is retained: there is no measured need to rewrite it. A local benchmark of optimized state/select operations was around 1 ms; this is not a performance guarantee.

Normal play reuses the existing Python user directory and configured model settings, including the existing advisor/opponent configuration. Godot presentation preferences are stored separately in Godot's `user://presentation.cfg`. A smoke run uses a temporary Python user directory, removes model credentials and proxy environment variables, and does not configure model clients.

Use **Settings → AI settings / Настройки → Настройки ИИ** to choose a provider, enter its key, and configure models, budgets, timeouts and offline mode. Presets cover OpenRouter, OpenAI, DeepSeek, Anthropic, Qwen (Singapore or China), Gemini, custom APIs and local OpenAI-compatible servers. The provider fills its base URL and example model; every model ID and endpoint remains editable. Use the model IDs and regional endpoint from your provider account: presets are examples, not availability or pricing guarantees. Anthropic uses its native Messages API; other presets use their OpenAI-compatible API.

There is **one active provider connection**, with **independent model IDs** for the opponent, advisors and experimental game master. These are not three independent provider connections. The opponent acts at adaptive difficulty (level 5); advisors use their text model; the game master uses its own model when explicitly enabled. A typed-decision opponent still needs a text model for the other roles. You control the selected superpower; this does not introduce an AI-versus-AI campaign mode.

Saved connection profiles and credentials are scoped to their provider. Switching providers clears any newly entered key and previews that provider’s saved profile or defaults; it does not save the selection until **Apply**. Existing keys are never returned to the screen. Leave the key field empty to retain the selected provider’s saved key, or use the explicit removal checkbox. Environment overrides and environment-supplied keys are identified in the dialog. Reading and applying settings do not contact a provider. **Test connection** uses the unsaved form and can send separate small probes for all three configured role models, outside the campaign call allowance; provider charges may apply. **Use built-in AI; disable network calls** keeps play offline.

Provider reference documentation: [OpenRouter](https://openrouter.ai/docs/api_reference/overview), [OpenAI](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create), [DeepSeek](https://api-docs.deepseek.com/api/create-chat-completion/), [Anthropic](https://platform.claude.com/docs/en/api/messages/create), [Qwen / Model Studio](https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope), and [Gemini](https://ai.google.dev/gemini-api/docs/openai).

[Provider settings](screenshots/godot-ai-settings.png) · [Separate role models](screenshots/godot-ai-models.png). These interface captures use local fixture settings and no provider credentials.

### Experimental AI game master

New campaigns start with **Experimental AI game master** unchecked. Opt in on the New game screen, or use **AI game master / ИИ-ведущий** during a supported single-player campaign. The panel shows whether the feature is enabled, its current status, the last error, and actual event history. Training and multiplayer do not support this experiment.

When enabled, the game master can generate an event for the initial campaign year and automatically when a year is committed, at any difficulty. **Generate this year’s event** offers the same annual opportunity manually; there is only one attempt per year, including a failed attempt, so reopening the panel cannot reroll an event. Requests use your configured provider and game-master model and may incur charges.

The Python engine validates proposed events and applies only bounded effects: unrest, an economic shock, a diplomatic incident or an eligible crisis flashpoint. Model text cannot issue arbitrary commands or replace the simulation’s policy and crisis rules. AI-generated dispatches are labeled, and the panel displays only backend event history. Missing configuration, offline mode, exhausted allowance or a failed/invalid model response leaves ordinary simulation available with a visible fallback status. Campaign saves retain the game-master state and history. [Game-master panel](screenshots/godot-game-master.png) shows an explicitly labeled local test fixture, captured without provider calls.

Level 5 uses the original model opponent and falls back visibly if it is unavailable. Crisis dialogue automatically requests the text model for both challenge directions; a visible loading state separates pending work from the final model or rules-based result. Training, disabled advisors, offline mode, missing configuration and provider failure have distinct localized status messages. Russian fallback advice uses the same verdicts as the game and current visible facts, including the policy, crisis rung and prestige estimate. Replies cannot change the completed mechanical decision. Changing settings invalidates old requests, preventing late replies from replacing newer settings or dialogue.

Advisor dialogs have **Latest answer**, **Conversation**, and **Track record** tabs. Transcripts stay separate by language; each advisor's prediction record is shared across languages. Pending forecasts resolve after the next year, and forecasts, aggregate calibration and bounded recent results survive save/load. The bridge save reserves at most 24 KB for this data, retaining pending forecasts and aggregate results before trimming old transcript text. This record belongs to the campaign; the old Qt application's cumulative memory file is untouched. Advice uses real money/personnel units and labels answers with their request year.

Russian localization covers the new Godot interface, country names, policy steps and limits, news, crisis summaries, tutorial and advisor output. It does not turn the old Qt application into a fully Russian interface.

![Start menu](screenshots/godot-start.png)

![Russian map interface](screenshots/godot-map-workspace.png)

[News briefing](screenshots/godot-news-feed.png) · [Learning session](screenshots/godot-tutorial.png) · [Practice crisis](screenshots/godot-tutorial-crisis.png) · [Policy controls](screenshots/godot-policy.png) · [Crisis](screenshots/godot-crisis.png) · [Advisor](screenshots/godot-advisor.png) · [Conversation](screenshots/godot-advisor-conversation.png) · [Advisor record](screenshots/godot-advisor-record.png) · [History](screenshots/godot-history.png) · [Scores](screenshots/godot-scores.png) · [AI settings](screenshots/godot-settings.png)

## Checks

```sh
python3 tests/test_engine_bridge.py
python3 tests/test_crisis_dialogue.py
python3 tests/test_advisor_facts.py
python3 tests/test_engine_campaigns.py
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -p 'test_*.py' -q
python3 tools/run_godot.py --headless --smoke-test
```

The Godot smoke run uses the actual start-menu buttons and exercises named saves, portable export/import, hotseat restoration, LAN hosting, shared-folder move submission, map selection, policy radio controls and Apply, an ordinary crisis, a year transition, save/load, reports and history tabs, AI settings, and the Russian UI. It presses the advisor's Ask button and checks the displayed reply. The learning session includes a prepared offline crisis: the normal rules process one escalation, a concession, the policy reversal and actual prestige loss. Further escalation is disabled within that lesson. Returning restores the exact campaign, RNG stream, conversations and pending crisis; return from training before starting a new game or saving.

A graphical run captures the main screen and additional tutorial, policy, crisis, advisor, reports and settings PNGs with `python3 tools/run_godot.py --smoke-test --language ru --screenshot /absolute/path/screenshot.png`.

Validation on 2026-11-10: all 144 tests in the combined local suite pass. These include ten full 1982–1990 campaign scenarios (both sides, levels 1–5), exact continuation after saving during a crisis, save/import/undo workflows, real two-service multiplayer, relay and reconnect, shared-folder turns, and Godot request, menu, interactive news and map regressions. The suite uses explicit offline mode or local model stand-ins, without paid provider calls. Targeted Godot tests were rerun after the final menu fixes.

Graphical source smoke runs pass at 1280×800 and 1024×720. Normal UI callbacks also exercise new campaign, named save, hotseat and session reopening. The map occupies about 78% of the logical viewport with drawers closed. Map report modes 0–57 match the Qt values and colors for every country; trade modes 58–59 read the actual trade tables. The import-isolation check verifies that the backend needs no Qt runtime.

Native Windows, Linux and Intel macOS build results are tracked in [PR #1 checks](https://github.com/or-sirina/balance-of-power/pull/1/checks). Automated headless checks do not replace interactive testing on target desktops.

## Assets and remaining migration

The map is exported from the existing game data by `tools/export_godot_assets.py`; regeneration requires Shapely 2.2. Relief, palette and synthesized cue provenance is documented in [asset attribution](../godot/assets/ATTRIBUTION.md). The generated synthesized WAV themes come from `Music.py`. Additional CC0 music credits, source links, and file details are in [music attribution](../godot/assets/music/ATTRIBUTION.md). Advisor photographs have individual public-domain or CC BY terms; retain their [attribution](../godot/assets/advisors/ATTRIBUTION.md) when distributing them.

Remaining work includes interactive testing on target desktops, native Apple Silicon packaging, and macOS signing and notarization. Godot saves are separate from Qt campaign files.
