#!/usr/bin/env python3
"""Build a platform-native frozen launcher and Godot export."""
import argparse
import hashlib
import importlib.metadata
import os
from pathlib import Path
import platform
import plistlib
import stat
import zipfile
import shutil
import subprocess
import sys
import sysconfig

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from run_godot import find_godot


def run(command):
    print('+', ' '.join(map(str, command)), flush=True)
    subprocess.run(command, check=True)


def extract_macos_app(archive, output):
    """Extract the Godot-produced app, rejecting paths outside its bundle."""
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        roots = {Path(entry.filename).parts[0] for entry in entries if Path(entry.filename).parts}
        if len(roots) != 1 or not next(iter(roots)).endswith('.app'):
            raise ValueError('Expected exactly one macOS .app in the exported archive')
        root = output.resolve()
        for entry in entries:
            dest = (root / entry.filename).resolve()
            if not dest.is_relative_to(root):
                raise ValueError('Unsafe path in exported macOS archive')
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError('Symlinks are not supported in the exported macOS archive')
            if entry.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with package.open(entry) as source, dest.open('wb') as target:
                    shutil.copyfileobj(source, target)
                if mode:
                    dest.chmod(mode & 0o777)
    app = output / next(iter(roots))
    with (app / 'Contents/Info.plist').open('rb') as handle:
        name = plistlib.load(handle)['CFBundleExecutable']
    if not isinstance(name, str) or Path(name).name != name or name in ('.', '..'):
        raise ValueError('Invalid CFBundleExecutable')
    executable = app / 'Contents/MacOS' / name
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError('Exported macOS app executable is missing or not executable')
    destination = output / 'bop-game.app'
    if app != destination:
        if destination.exists():
            shutil.rmtree(destination)
        app.rename(destination)
    archive.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--godot')
    parser.add_argument('--platform', choices=('linux', 'windows', 'macos'), default={'Linux':'linux','Windows':'windows','Darwin':'macos'}.get(platform.system()))
    args = parser.parse_args()
    current = {'Linux':'linux','Windows':'windows','Darwin':'macos'}.get(platform.system())
    if not current or args.platform != current:
        parser.error('Build the frozen launcher on the target operating system; cross-freezing is unsupported.')
    godot = find_godot(args.godot)
    project = ROOT / 'godot'
    output = ROOT / 'dist-godot' / args.platform
    work = ROOT / 'dist-godot' / 'build' / args.platform
    output.mkdir(parents=True, exist_ok=True)
    run([godot, '--headless', '--editor', '--path', str(project), '--import', '--quit'])
    preset = {'linux':'Linux','windows':'Windows','macos':'macOS'}[args.platform]
    client = {'linux':'bop-game','windows':'bop-game.exe','macos':'bop-game.zip'}[args.platform]
    run([godot, '--headless', '--path', str(project), '--export-release', preset, str(output / client)])
    if args.platform == 'macos':
        extract_macos_app(output / client, output)
    run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--name', 'BalanceOfPower',
         '--distpath', str(work / 'dist'), '--workpath', str(work / 'work'), '--specpath', str(work),
         '--paths', str(ROOT), '--add-data', str(ROOT / 'data') + os.pathsep + 'data',
         '--collect-submodules', 'EngineBridge', '--collect-submodules', 'GameLogic', str(ROOT / 'tools/run_godot.py')])
    built = work / 'dist' / 'BalanceOfPower'
    for item in built.iterdir():
        dest = output / item.name
        if item.is_dir(): shutil.copytree(item, dest, dirs_exist_ok=True)
        else: shutil.copy2(item, dest)
    credits = output / 'credits'
    credits.mkdir(exist_ok=True)
    for source in (ROOT / 'godot/assets/advisors/ATTRIBUTION.md', ROOT / 'godot/assets/advisors/manifest.json', ROOT / 'godot/assets/music/ATTRIBUTION.md', ROOT / 'godot/assets/music/licensed_tracks.json'):
        shutil.copy2(source, credits / (source.parent.name + '-' + source.name))
    for name in ('GODOT-LICENSE.txt', 'GODOT-COPYRIGHT.txt'):
        shutil.copy2(ROOT / 'packaging/godot' / name, credits / name)
    pyinstaller = importlib.metadata.distribution('pyinstaller')
    license_file = next((pyinstaller.locate_file(f) for f in pyinstaller.files or ()
                         if str(f).endswith('licenses/COPYING.txt')), None)
    if license_file is None:
        raise RuntimeError('Could not find the installed PyInstaller license')
    shutil.copy2(license_file, credits / 'PYINSTALLER-LICENSE.txt')
    candidates = (Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt', Path(sys.base_prefix) / 'LICENSE.txt')
    python_license = next((p for p in candidates if p.is_file()), None)
    if python_license is None and sys.version_info[:3] == (3, 12, 10):
        # Official CPython v3.12.10 LICENSE, vendored for hosts that omit it.
        fallback = ROOT / 'packaging/godot/CPYTHON-3.12.10-LICENSE.txt'
        expected = '3b2f81fe21d181c499c59a256c8e1968455d6689d269aa85373bfb6af41da3bf'
        if hashlib.sha256(fallback.read_bytes()).hexdigest() != expected:
            raise RuntimeError('Vendored CPython license checksum mismatch')
        python_license = fallback
    if python_license is None:
        raise RuntimeError('Could not find the matching Python runtime license in ' + ', '.join(map(str, candidates)))
    shutil.copy2(python_license, credits / 'PYTHON-LICENSE.txt')
    shutil.copy2(ROOT / 'packaging/godot/PLAY-README.txt', output / 'README.txt')
    archive = shutil.make_archive(str(output.parent / ('BalanceOfPower-' + args.platform)),
                                  'gztar' if args.platform != 'windows' else 'zip',
                                  root_dir=output.parent, base_dir=output.name)
    print('Built:', output)
    print('Archive:', archive)
    if args.platform == 'macos':
        print('macOS signing/notarization are not configured; native validation is required.')

if __name__ == '__main__': main()
