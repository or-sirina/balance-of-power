"""
Networking support for Balance of Power.

Sub-modules
-----------
``Protocol``    – framing, message encoding, the wire vocabulary.
``State``       – translating a live :class:`GameLogic.World.World` to and from
                  plain JSON so it can be replicated between machines.
``Discovery``   – UDP broadcast so that games on the local network find each
                  other without anyone typing an IP address.
``Session``     – the Qt object that owns the sockets and drives the game flow,
                  including coming back from a dropped connection.
``GameFile``    – the portable, versioned, checksummed game file: one document
                  that can be emailed, and the format play-by-mail moves in.
``MailGame``    – play-by-mail over a shared folder, for networks where the two
                  machines cannot open a connection to each other at all.
``Diagnostics`` – the bounded checks behind the lobby's "Test connection"
                  button: is the port listened on, is the peer visible, does
                  UDP discovery answer.
"""

PROTOCOL_VERSION = 2

#: Application-level name used in the UDP discovery handshake.
DISCOVERY_MAGIC = "BOP-DISCOVER-1"
DISCOVERY_PORT = 45455

from .Protocol import FrameReader, encode_message
from .State import apply_state, apply_state_safely, world_to_state

__all__ = [
    "PROTOCOL_VERSION", "DISCOVERY_MAGIC", "DISCOVERY_PORT",
    "FrameReader", "encode_message", "world_to_state", "apply_state", "apply_state_safely",
]
