#!/usr/bin/env python3
"""Start the local engine bridge and the Godot client together."""
import argparse
import glob
import os
import plistlib
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def find_godot(explicit):
    candidates = [explicit, os.environ.get("BOP_GODOT"), shutil.which("godot"),
                  shutil.which("godot4"), "/Applications/Godot.app/Contents/MacOS/Godot"]
    candidates += sorted(glob.glob(str(Path.home() / ".local/share/bop-tools/godot-*/Godot*linux.x86_64")), reverse=True)
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise FileNotFoundError("Godot executable not found; pass --godot or set BOP_GODOT")


def isolate_smoke():
    for key in list(os.environ):
        if key.startswith("BOP_LLM_") or key in {
            "OPENROUTER_API_KEY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
            "http_proxy", "https_proxy", "all_proxy", "REQUESTS_CA_BUNDLE",
            "SSL_CERT_FILE", "CURL_CA_BUNDLE",
        }:
            del os.environ[key]
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot", help="path to the Godot executable")
    parser.add_argument("--exported-client", type=Path,
                        help="run an exported game executable instead of the Godot editor")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--language", choices=("en", "ru"))
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--screenshot", type=Path, help="absolute PNG output path")
    args = parser.parse_args()
    if args.screenshot and (not args.screenshot.is_absolute() or args.screenshot.suffix.lower() != ".png"):
        parser.error("--screenshot must be an absolute PNG path")
    exported_client = args.exported_client
    if exported_client is None and getattr(sys, "frozen", False):
        bundle_dir = Path(sys.executable).resolve().parent
        if sys.platform == "darwin":
            app = bundle_dir / "bop-game.app" / "Contents"
            try:
                with (app / "Info.plist").open("rb") as handle:
                    name = plistlib.load(handle)["CFBundleExecutable"]
                if not isinstance(name, str) or Path(name).name != name or name in (".", ".."):
                    raise ValueError("invalid bundle executable")
                exported_client = app / "MacOS" / name
            except (OSError, ValueError, KeyError, plistlib.InvalidFileException) as exc:
                parser.error("could not locate exported macOS app: %s" % exc)
        else:
            filename = "bop-game.exe" if os.name == "nt" else "bop-game"
            exported_client = bundle_dir / filename
            if not exported_client.is_file() and os.name != "nt":
                exported_client = exported_client.with_name("bop-game.x86_64")
    if exported_client is not None:
        exported_client = exported_client.resolve()
        if not exported_client.is_file() or not os.access(exported_client, os.X_OK):
            parser.error("exported game executable was not found: %s" % exported_client)
        executable = str(exported_client)
    else:
        try:
            executable = find_godot(args.godot)
        except FileNotFoundError as exc:
            parser.error(str(exc))
    with tempfile.TemporaryDirectory(prefix="bop_godot_smoke_") if args.smoke_test else _null_context() as user_dir:
        if args.smoke_test:
            isolate_smoke()
            os.environ["BOP_USER_DIR"] = user_dir
        if exported_client is None:
            print("Importing Godot project assets...", flush=True)
            try:
                imported = subprocess.run([executable, "--headless", "--editor", "--path",
                                           str(ROOT / "godot"), "--import", "--quit"])
            except KeyboardInterrupt:
                return 130
            if imported.returncode:
                print("Godot asset import failed.", file=sys.stderr)
                return imported.returncode
        sys.path.insert(0, str(ROOT))
        import EngineBridge
        if args.smoke_test:
            service = EngineBridge.GameService()
        else:
            models = EngineBridge.configured_client_factory()
            service = EngineBridge.GameService(model_client_factory=models, opponent_factory=models.opponent)
        server = EngineBridge.create_server(service=service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        process = None
        old_sigterm = signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        try:
            command = [executable]
            if args.headless:
                command.append("--headless")
            if exported_client is None:
                command += ["--path", str(ROOT / "godot")]
            command += ["--", "--backend-url",
                        "http://127.0.0.1:%s" % server.server_address[1],
                        "--backend-token", server.token]
            if args.language:
                command += ["--language", args.language]
            if args.smoke_test:
                command.append("--smoke-test")
            if args.screenshot:
                command += ["--screenshot", str(args.screenshot)]
            process = subprocess.Popen(command)
            try:
                return process.wait()
            except KeyboardInterrupt:
                return 130
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            signal.signal(signal.SIGTERM, old_sigterm)
            server.shutdown()
            thread.join()
            server.server_close()


class _null_context:
    def __enter__(self):
        return None

    def __exit__(self, *args):
        return False


if __name__ == "__main__":
    sys.exit(main())
