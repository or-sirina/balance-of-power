#!/usr/bin/env python3
"""Install verified official Godot 4.7.2 editor and templates for native CI."""
import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import urllib.request
import zipfile

VERSION = '4.7.2-stable'
BASE = 'https://github.com/godotengine/godot-builds/releases/download/' + VERSION + '/'
ASSETS = {
    'linux': ('Godot_v4.7.2-stable_linux.x86_64.zip', 'cadd3204e728a35d3f13adb7fd0d7902636b79f6b95c40c265eb73b6c35329e4'),
    'windows': ('Godot_v4.7.2-stable_win64.exe.zip', '731980f9608d61333e5baf54a2ef17210acc7a538446c0cb9969f002aca1e953'),
    'macos': ('Godot_v4.7.2-stable_macos.universal.zip', 'c58a24e31d720be9d62f60cb5627c4e695fb72f21b0cfe1bc9ccaa9a3b3ba63e'),
    'templates': ('Godot_v4.7.2-stable_export_templates.tpz', 'f298490b8d44d934be425a5a65a51bf15f422428b229a06a6e11d9ffea248011'),
}


def verified(key, cache):
    name, expected = ASSETS[key]
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / name
    if not archive.is_file():
        part = archive.with_suffix(archive.suffix + '.part')
        try:
            with urllib.request.urlopen(BASE + name, timeout=120) as response, part.open('wb') as out:
                shutil.copyfileobj(response, out)
            part.replace(archive)
        finally:
            part.unlink(missing_ok=True)
    digest = hashlib.sha256()
    with archive.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    if digest.hexdigest() != expected:
        raise ValueError('SHA-256 mismatch for ' + name)
    return archive


def extract(archive, destination, strip_prefix=None):
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            parts = PurePosixPath(item.filename).parts
            if strip_prefix:
                if not parts or parts[0] != strip_prefix:
                    raise ValueError('Unexpected archive root: ' + item.filename)
                parts = parts[1:]
            if not parts:
                continue
            if any(part in ('..', '.', '/') or '\\' in part or ':' in part for part in parts):
                raise ValueError('Unsafe archive path: ' + item.filename)
            mode = item.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError('Unexpected symlink: ' + item.filename)
            target = destination.joinpath(*parts)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(item) as source, target.open('wb') as out:
                    shutil.copyfileobj(source, out)
                if mode:
                    target.chmod(mode & 0o777)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=Path.home() / '.cache/bop-godot-ci')
    parser.add_argument('--install-dir', type=Path, default=Path.home() / '.local/share/bop-godot-ci')
    parser.add_argument('--github-env', type=Path, help='write BOP_GODOT to GitHub Actions environment file')
    args = parser.parse_args()
    system = {'Linux': 'linux', 'Windows': 'windows', 'Darwin': 'macos'}.get(platform.system())
    arch = platform.machine().lower()
    if not system or (system in ('linux', 'windows') and arch not in ('x86_64', 'amd64')):
        parser.error('Unsupported host OS or architecture')
    editor_archive = verified(system, args.cache)
    templates_archive = verified('templates', args.cache)
    editor = args.install_dir / 'editor'
    extract(editor_archive, editor)
    if system == 'linux':
        executable = editor / 'Godot_v4.7.2-stable_linux.x86_64'
        templates = Path.home() / '.local/share/godot/export_templates/4.7.2.stable'
    elif system == 'windows':
        executable = editor / 'Godot_v4.7.2-stable_win64.exe'
        templates = Path(os.environ['APPDATA']) / 'Godot/export_templates/4.7.2.stable'
    else:
        executable = editor / 'Godot.app/Contents/MacOS/Godot'
        templates = Path.home() / 'Library/Application Support/Godot/export_templates/4.7.2.stable'
    if not executable.is_file():
        raise FileNotFoundError('Editor executable missing: ' + str(executable))
    if system != 'windows':
        executable.chmod(executable.stat().st_mode | 0o111)
    extract(templates_archive, templates, strip_prefix='templates')
    if args.github_env:
        with args.github_env.open('a', encoding='utf-8') as out:
            out.write('BOP_GODOT=' + str(executable.resolve()) + '\n')
    print('Verified Godot editor:', executable)
    print('Verified export templates:', templates)


if __name__ == '__main__':
    main()
