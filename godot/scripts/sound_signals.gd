extends Node
## Reuse the original synthesized turn/crisis/endgame cues without Qt.
const TRACKS = {
 "turn": preload("res://assets/sfx/turn.wav"),
 "crisis": preload("res://assets/sfx/crisis.wav"),
 "endgame": preload("res://assets/sfx/endgame.wav")
}
var player: AudioStreamPlayer
var year := 0
var crisis := false
var ended := false

func observe(state: Dictionary, enabled: bool, volume_db: float, quiet: bool) -> void:
 if state.is_empty(): return
 var next_year := int(state.get("year", 0))
 var next_crisis := bool(state.get("crisis", {}).get("active", false)) or state.get("multiplayer", {}).get("duel") is Dictionary
 var next_ended := bool(state.get("ended", false))
 var cue := ""
 if next_ended and not ended: cue = "endgame"
 elif next_crisis and not crisis: cue = "crisis"
 elif year > 0 and next_year > year: cue = "turn"
 year = next_year
 crisis = next_crisis
 ended = next_ended
 if not enabled or quiet or cue.is_empty(): return
 if not is_instance_valid(player):
  player = AudioStreamPlayer.new()
  add_child(player)
 player.volume_db = minf(0.0, volume_db + 6.0)
 player.stream = TRACKS[cue]
 player.play()
