"""Run a local bridge; the launcher consumes the single startup JSON line."""

import json

from .server import create_server
from .models import configured_client_factory
from .service import GameService


def main():
    models = configured_client_factory()
    server = create_server(GameService(model_client_factory=models, opponent_factory=models.opponent))
    print(json.dumps({"host": server.server_address[0], "port": server.server_address[1],
                      "token": server.token}), flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
