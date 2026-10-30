"""
Wire protocol: how bytes become messages.

Frames are length-prefixed so a QTcpSocket's arbitrary chunking never matters::

    +--------+--------+--------+-------------------+
    | magic  | length | flags  | JSON payload      |
    | 4 B    | 4 B BE | 1 B    | `length` bytes    |
    +--------+--------+--------+-------------------+

Flag bit 0 means the payload is zlib-compressed.  A full world snapshot is a few
hundred kilobytes of JSON but well under a hundred kilobytes deflated, which
keeps policy updates comfortable even on a busy wireless LAN.
"""

import json
import struct
import zlib

MAGIC = b"BOP1"
_HEADER = struct.Struct("!4sIB")
FLAG_COMPRESSED = 0x01

#: Refuse absurd frames rather than trying to allocate them.
MAX_FRAME_SIZE = 32 * 1024 * 1024

#: Payloads above this size are compressed before being sent.
COMPRESS_THRESHOLD = 1024


class ProtocolError(Exception):
    """Raised when a peer sends something that is not a valid frame."""


def bounded_decompress(data, limit=MAX_FRAME_SIZE):
    """zlib-decompress ``data`` but never produce more than ``limit`` bytes.

    A few kilobytes of zeros inflate to gigabytes; the frame-size limit alone
    does not protect against that, so the output is capped as well.
    """
    inflater = zlib.decompressobj()
    try:
        out = inflater.decompress(data, limit + 1)
        if len(out) > limit or inflater.unconsumed_tail:
            raise ProtocolError("decompressed data exceeds the %d byte limit" % limit)
        if not inflater.eof:
            raise ProtocolError("corrupt compressed frame: truncated stream")
    except zlib.error as exc:
        raise ProtocolError("corrupt compressed frame: %s" % exc)
    return out


def encode_message(message):
    """Serialise ``message`` (a JSON-able object) into one frame."""
    payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    flags = 0
    if len(payload) > COMPRESS_THRESHOLD:
        compressed = zlib.compress(payload, 6)
        if len(compressed) < len(payload):
            payload, flags = compressed, FLAG_COMPRESSED
    return _HEADER.pack(MAGIC, len(payload), flags) + payload


class FrameReader:
    """Incremental parser: feed it bytes, get back whole messages."""

    def __init__(self, max_frame_size=MAX_FRAME_SIZE):
        self._buffer = bytearray()
        self._max_frame_size = max_frame_size

    def feed(self, data):
        """Append received bytes and return the list of complete messages."""
        if data:
            self._buffer.extend(data)
        messages = []
        while True:
            if len(self._buffer) < _HEADER.size:
                break
            magic, length, flags = _HEADER.unpack_from(self._buffer, 0)
            if magic != MAGIC:
                raise ProtocolError("bad frame magic %r" % (bytes(magic),))
            if length > self._max_frame_size:
                raise ProtocolError("frame of %d bytes exceeds the limit" % length)
            if len(self._buffer) < _HEADER.size + length:
                break
            payload = bytes(self._buffer[_HEADER.size:_HEADER.size + length])
            del self._buffer[:_HEADER.size + length]
            if flags & FLAG_COMPRESSED:
                payload = bounded_decompress(payload, self._max_frame_size)
            try:
                messages.append(json.loads(payload.decode("utf-8")))
            except (UnicodeDecodeError, ValueError, RecursionError) as exc:
                raise ProtocolError("frame is not valid JSON: %s" % exc)
        return messages

    def pending(self):
        return len(self._buffer)

    def reset(self):
        self._buffer.clear()


# --- message vocabulary -----------------------------------------------------
#
# Keeping the names in one place makes the protocol easy to grep for and stops
# the two halves of the connection from drifting apart.

class Message:
    # Handshake / lobby
    HELLO = "hello"
    WELCOME = "welcome"
    LOBBY = "lobby"
    READY = "ready"
    START = "start"
    BYE = "bye"

    # Gameplay
    ACTION = "action"          # client -> host: enact a policy / end a turn
    SNAPSHOT = "snapshot"      # host -> client: authoritative world state
    EVENT = "event"            # host -> client: a status line worth showing
    CRISIS = "crisis"          # host -> client: you must answer a crisis
    CRISIS_REPLY = "crisis_reply"
    CHAT = "chat"
    PING = "ping"
    PONG = "pong"


class Action:
    """Player intents, sent from a client to the authoritative host."""

    POLICY = "policy"          # {action, target, value}
    END_TURN = "end_turn"
    READY = "ready"
    CHAT = "chat"
    CRISIS = "crisis"          # {tough: bool}
