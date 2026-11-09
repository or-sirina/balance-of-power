"""Desktop game-engine bridge; no Qt or model calls on import/startup."""

from .service import GameService
from .server import create_server
from .models import configured_client_factory

__all__ = ["GameService", "create_server", "configured_client_factory"]
