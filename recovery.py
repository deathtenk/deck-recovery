#!/usr/bin/env python3
"""Selective SteamOS utilities recovery; standard library only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
import zipfile

BASE = Path(__file__).resolve().parent
PLUGINS = {'decktation': 'decktation', 'css-loader': 'SDH-CssLoader',
           'steamcord': 'Steamcord', 'deckshots': 'deckshots',
           'pause-games': 'SDH-PauseGames', 'web-browser': 'DeckWebBrowser',
           'volume-mixer': 'VolumeMixer-decky', 'audio-loader': 'SDH-AudioLoader',
           'volume-boost': 'volume-boost'}
DEFAULT = ['homebrew', 'decky', 'decktation', 'css-loader', 'steamcord']
ALL = DEFAULT + [x for x in PLUGINS if x not in DEFAULT] + ['lg-tv', 'drive-mount', 'zen']
SERVICES = {'decky': ['plugin_loader'], 'lg-tv': ['lg-tv-control-steam-button', 'lg-tv-control-resume'],
            'drive-mount': ['mount-2tb'], 'zen': ['zen-kernel-reapply', 'zen-kernel-notify']}

def run(*args):
    subprocess.run([str(x) for x in args], check=True)

def digest(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()

def csv(value):
    return [x.strip() for x in value.split(',') if x.strip()]

def selection(a):
    selected = set(csv(a.components) if a.components is not None else ALL if a.full else DEFAULT)
    selected.update(csv(a.enable))
    disabled = set(csv(a.disable))
    if (selected | disabled) - set(ALL):
        raise ValueError('Unknown components: ' + ', '.join(sorted((selected | disabled) - set(ALL))))
    selected -= disabled
    dependencies = set()
    if selected & set(PLUGINS):
        dependencies.add('decky')
    if 'decky' in selected or 'decky' in dependencies:
        dependencies.add('homebrew')
    if dependencies & disabled:
        raise ValueError('Disabled dependency: ' + ', '.join(sorted(dependencies & disabled)))
    return [c for c in ALL if c in selected | dependencies]

def paths(c, config=False):
    if c in PLUGINS:
        name = PLUGINS[c]
        if not config:
            return ['homebrew/plugins/' + name]
        result = ['homebrew/settings/' + name, 'homebrew/data/' + name]
        if c == 'css-loader': result += ['homebrew/themes']
        if c == 'audio-loader': result += ['homebrew/sounds']
        if c == 'steamcord': result += ['.config/steamcord-' + n + '.json' for n in ['notify', 'rpc', 'audio', 'stream', 'guild-order', 'hidden-guilds', 'input', 'overlay']]
        return result
    if c == 'decky':
        return ['homebrew/settings/loader.json'] if config else ['homebrew/services/PluginLoader', 'homebrew/services/.loader.version']
    if c == 'lg-tv':
        return ['.config/lg-tv-control/env', '.lg_webos_key.json'] if config else ['.local/bin/lg-tv-control'] + ['/etc/systemd/system/' + s + '.service' for s in SERVICES[c]]
    if c == 'drive-mount':
        return [] if config else ['/etc/systemd/system/mount-2tb.service', '/etc/atomic-update.conf.d/mount-2tb.conf']
    if c == 'zen':
        return [] if config else ['.zen-kernel/zen-kernel.sh'] + ['/etc/systemd/system/' + s + '.service' for s in SERVICES[c]] + ['/etc/atomic-update.conf.d/zen-kernel.conf']
    return []

def source(home, root, rel):
    return root / rel.lstrip('/') if rel.startswith('/') else home / rel

def write_zip(out, home, root, rels):
    count = 0
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for rel in rels:
            p = source(home, root, rel)
            if not p.exists(): continue
            entries = [p] if p.is_file() else sorted(p.rglob('*'))
            for f in entries:
                if f.is_symlink():
                    raise ValueError('Symlink needs explicit handling; refusing capture: ' + str(f))
                if not f.is_file() or '__pycache__' in f.parts or f.suffix == '.pyc': continue
                name = ('system/' + str(f.relative_to(root))) if rel.startswith('/') else ('home/' + str(f.relative_to(home)))
                try:
                    z.write(f, name)
                except PermissionError:
                    info = zipfile.ZipInfo(name)
                    info.external_attr = f.stat().st_mode << 16
                    try:
                        data = subprocess.run(['sudo', '-n', 'cat', '--', str(f)], check=True, capture_output=True).stdout
                    except subprocess.CalledProcessError as e:
                        raise ValueError('Privileged capture required for ' + str(f) + '; run sudo -v first, then retry with a new output directory') from e
                    z.writestr(info, data)
                count += 1
    return count

def capture(a, selected):
    if not a.output: raise ValueError('capture requires --output')
    out = Path(a.output).resolve()
    if out.exists(): raise ValueError('Output already exists; choose a new dated directory')
    if out.is_relative_to(a.home / 'homebrew'):
        raise ValueError('Output cannot be inside the captured homebrew tree')
    out.mkdir(parents=True, mode=0o700)
    manifest = {'schema': 1, 'components': {}, 'created': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'kernel': platform.release(), 'notes': 'Private configuration; encrypt before off-device storage.'}
    for c in selected:
        entry = {}
        for kind in ['software', 'config']:
            name = c + '-' + kind + '.zip'
            if write_zip(out / name, a.home, a.root, paths(c, kind == 'config')):
                entry[kind] = {'file': name, 'sha256': digest(out / name)}
            else: (out / name).unlink()
        manifest['components'][c] = entry
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    if os.getuid() == 0 and os.environ.get('SUDO_UID'):
        uid, gid = int(os.environ['SUDO_UID']), int(os.environ['SUDO_GID'])
        for f in [out, *out.rglob('*')]: os.chown(f, uid, gid)
    print('Captured:', out, '\nKeep this directory private and encrypt it before storage. No games or personal files captured.')

def valid_member(info):
    p = Path(info.filename)
    if p.is_absolute() or '..' in p.parts or stat.S_ISLNK(info.external_attr >> 16):
        raise ValueError('Unsafe archive member: ' + info.filename)

def unpack(archive, dest):
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist(): valid_member(info)
        z.extractall(dest)
        for info in z.infolist():
            p = dest / info.filename
            mode = (info.external_attr >> 16) & 0o777
            if p.is_file() and mode: p.chmod(mode)

def fetch(spec, dest):
    url = spec['url']
    print('Downloading pinned artifact:', url, flush=True)
    if not url.startswith('https://'): raise ValueError('Downloads require HTTPS')
    with urllib.request.urlopen(url, timeout=60) as r, open(dest, 'wb') as f:
        shutil.copyfileobj(r, f)
    if digest(dest) != spec['sha256']: raise ValueError('Download checksum mismatch: ' + url)

def bundle(a, selected):
    if a.stateless or (a.config == 'defaults' and not a.backup): return {}
    if not a.backup: raise ValueError('Configuration restoration requires --backup; use --stateless for fresh utilities')
    directory = Path(a.backup).resolve()
    data = json.loads((directory / 'manifest.json').read_text())
    if data.get('schema') != 1: raise ValueError('Unsupported backup schema')
    result = {}
    for c in selected:
        if c not in data['components']: raise ValueError('Component not captured: ' + c)
        result[c] = {}
        for kind, spec in data['components'][c].items():
            if a.config == 'defaults' and kind == 'config': continue
            p = directory / spec['file']
            if p.parent != directory: raise ValueError('Unsafe bundle filename')
            if digest(p) != spec['sha256']: raise ValueError('Corrupt backup: ' + p.name)
            result[c][kind] = p
    return result

class Installer:
    def __init__(self, a):
        self.a = a
        self.saved = a.home / '.local/state/deck-recovery' / (str(time.time_ns()) + '-replacements')
        self.saved.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.saved.chmod(0o700)
    def replace(self, src, dst):
        # sudo inherits our private umask. Repair/create home ancestors before
        # inspecting targets, including directories left by an interrupted run.
        if not self.a.sandbox and dst.is_relative_to(self.a.home):
            parents = list(reversed(dst.parent.relative_to(self.a.home).parents))
            directories = [self.a.home / p for p in parents if p != Path('.')] + [dst.parent]
            for directory in directories:
                result = subprocess.run(['sudo', 'test', '-L', str(directory)])
                if result.returncode == 0: raise ValueError('Refusing symlink ancestor: ' + str(directory))
                if result.returncode != 1: raise ValueError('Cannot inspect target ancestor: ' + str(directory))
                run('sudo', 'mkdir', '-p', directory)
                run('sudo', 'chown', str(os.getuid()) + ':' + str(os.getgid()), directory)
                run('sudo', 'chmod', 'u+rwx', directory)
        if any(p.is_symlink() for p in [dst, *dst.parents]): raise ValueError('Refusing symlink target or ancestor: ' + str(dst))
        if dst.exists():
            saved = self.saved / ('system' if dst.is_relative_to(self.a.root / 'etc') else 'home') / str(dst).lstrip('/')
            saved.parent.mkdir(parents=True, exist_ok=True)
            if self.a.sandbox: shutil.move(str(dst), saved)
            else: run('sudo', 'cp', '-a', dst, saved); run('sudo', 'rm', '-rf', '--', dst)
        if self.a.sandbox:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir(): shutil.copytree(src, dst)
            else: shutil.copy2(src, dst)
        else:
            if dst.is_relative_to(self.a.root / 'etc'):
                run('sudo', 'install', '-d', '-m', '0755', dst.parent)
            else:
                run('sudo', 'mkdir', '-p', dst.parent)
            run('sudo', 'cp', '-a', src, dst)
            if dst.is_relative_to(self.a.root / 'etc') and src.is_file(): run('sudo', 'chmod', '0644', dst)
            if dst.is_relative_to(self.a.home): run('sudo', 'chown', '-R', str(os.getuid()) + ':' + str(os.getgid()), dst)
    def archive(self, archive, c, config=False):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); unpack(archive, tmp)
            allowed = paths(c, config)
            # Restore only explicitly owned paths; reject unexpected payloads before writes.
            for f in tmp.rglob('*'):
                if not f.is_file(): continue
                rel = f.relative_to(tmp).as_posix()
                if not any(rel == ('system/' + p.lstrip('/') if p.startswith('/') else 'home/' + p) or rel.startswith(('system/' + p.lstrip('/') if p.startswith('/') else 'home/' + p) + '/') for p in allowed):
                    raise ValueError('Unexpected component file: ' + rel)
            for p in allowed:
                src = tmp / ('system/' + p.lstrip('/') if p.startswith('/') else 'home/' + p)
                if src.exists(): self.replace(src, source(self.a.home, self.a.root, p))
    def reset(self, c):
        for p in paths(c, True):
            dst = source(self.a.home, self.a.root, p)
            if dst.exists():
                with tempfile.TemporaryDirectory() as tmp:
                    empty = Path(tmp) / 'empty'
                    if dst.is_dir(): empty.mkdir()
                    else: empty.write_text('{}\n' if dst.suffix == '.json' else '')
                    self.replace(empty, dst)
                    if self.a.sandbox: dst.unlink() if dst.is_file() else dst.rmdir()
                    else: run('sudo', 'rm', '-rf', '--', dst)

def restore(a, selected, payload, specs):
    ins = Installer(a)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp); staged = {}
        # Stage and validate ALL downloads and archives before changing the target.
        for c in selected:
            if 'software' in payload.get(c, {}):
                staged[c] = payload[c]['software']
            elif c in specs and c != 'homebrew':
                staged[c] = tmp / (c + '.asset'); fetch(specs[c], staged[c])
            elif c != 'homebrew': raise ValueError('No pinned fresh installer for ' + c + '; capture it and use configuration restoration')
            if 'software' in payload.get(c, {}) and not zipfile.is_zipfile(staged[c]): raise ValueError('Invalid captured archive: ' + c)
            if c in staged and zipfile.is_zipfile(staged[c]):
                unpack(staged[c], tmp / (c + '-check'))
                if c in PLUGINS and 'software' not in payload.get(c, {}):
                    manifests = list((tmp / (c + '-check')).rglob('plugin.json'))
                    if len(manifests) != 1 or not (manifests[0].parent / 'dist/index.js').is_file():
                        raise ValueError('Invalid plugin package: ' + c)
            for kind, archive in payload.get(c, {}).items():
                allowed = [('system/' + p.lstrip('/') if p.startswith('/') else 'home/' + p) for p in paths(c, kind == 'config')]
                with zipfile.ZipFile(archive) as z:
                    for info in z.infolist():
                        valid_member(info)
                        if not info.is_dir() and not any(info.filename == p or info.filename.startswith(p + '/') for p in allowed):
                            raise ValueError('Unexpected component file: ' + info.filename)
        if not a.sandbox:
            if os.getuid() == 0 or a.home != Path('/home/deck') or platform.machine() != 'x86_64':
                raise ValueError('Live restoration requires the deck user on x86_64 with /home/deck')
            if 'ID=steamos' not in Path('/etc/os-release').read_text(): raise ValueError('Live restoration requires SteamOS')
            run('sudo', '-v')
            if 'lg-tv' in selected and 'config' not in payload.get('lg-tv', {}) and not (a.home / '.config/lg-tv-control/env').is_file():
                raise ValueError('LG TV requires a captured configuration or an existing environment file')
            if 'drive-mount' in selected and not Path('/dev/disk/by-uuid/5d5c2fea-90d4-4ed5-bbbf-0194853ae1c2').exists():
                raise ValueError('Expected external drive is missing')
        loader_stopped = False
        try:
            if not a.sandbox and 'decky' in selected:
                status = subprocess.run(['systemctl', 'is-active', '--quiet', 'plugin_loader']).returncode
                if status == 0: run('sudo', 'systemctl', 'stop', 'plugin_loader'); loader_stopped = True
            for c in selected:
                print('Installing:', c, flush=True)
                if c == 'homebrew':
                    if a.sandbox:
                        marker = a.root / 'home/linuxbrew/.linuxbrew/bin/brew'; marker.parent.mkdir(parents=True, exist_ok=True); marker.write_text('sandbox marker\n')
                    elif not Path('/home/linuxbrew/.linuxbrew/bin/brew').exists():
                        script = tmp / 'brew.sh'; fetch(specs['homebrew'], script)
                        subprocess.run(['/bin/bash', str(script)], check=True, env={**os.environ, 'NONINTERACTIVE': '1'})
                    continue
                if 'software' in payload.get(c, {}): ins.archive(staged[c], c)
                elif c in PLUGINS:
                    tree = tmp / (c + '-check')
                    manifests = list(tree.rglob('plugin.json'))
                    if len(manifests) != 1 or not (manifests[0].parent / 'dist/index.js').is_file(): raise ValueError('Invalid plugin package: ' + c)
                    ins.replace(manifests[0].parent, a.home / 'homebrew/plugins' / PLUGINS[c])
                elif c == 'decky':
                    ins.replace(staged[c], a.home / 'homebrew/services/PluginLoader')
                    if a.sandbox: (a.home / 'homebrew/services/PluginLoader').chmod(0o755)
                    else: run('sudo', 'chmod', '0755', a.home / 'homebrew/services/PluginLoader')
                    version = tmp / 'loader-version'; version.write_text('v3.2.6\n')
                    ins.replace(version, a.home / 'homebrew/services/.loader.version')
                if a.reset_config: ins.reset(c)
                if 'config' in payload.get(c, {}): ins.archive(payload[c]['config'], c, True)
                if c == 'decky':
                    enable_cef(a)
                    unit = tmp / 'plugin_loader.service'
                    unit.write_text('[Unit]\nDescription=SteamDeck Plugin Loader\nAfter=network.target\n[Service]\nType=simple\nUser=root\nRestart=always\nKillMode=process\nTimeoutStopSec=15\nExecStart=/home/deck/homebrew/services/PluginLoader\nWorkingDirectory=/home/deck/homebrew/services\nEnvironment=UNPRIVILEGED_PATH=/home/deck/homebrew\nEnvironment=PRIVILEGED_PATH=/home/deck/homebrew\n[Install]\nWantedBy=multi-user.target\n')
                    ins.replace(unit, a.root / 'etc/systemd/system/plugin_loader.service')
            for c in selected:
                if c in SERVICES:
                    keep = tmp / (c + '-keep.conf')
                    keep.write_text(''.join('/etc/systemd/system/' + s + '.service\n/etc/systemd/system/*.target.wants/' + s + '.service\n' for s in SERVICES[c]))
                    ins.replace(keep, a.root / ('etc/atomic-update.conf.d/deck-recovery-' + c + '.conf'))
            if not a.sandbox:
                run('sudo', 'systemctl', 'daemon-reload')
                for c in selected:
                    for s in SERVICES.get(c, []): run('sudo', 'systemctl', 'enable', s)
                if 'lg-tv' in selected: run('sudo', 'systemctl', 'restart', 'lg-tv-control-steam-button')
                if 'drive-mount' in selected: run('sudo', 'systemctl', 'start', 'mount-2tb')
                if 'zen' in selected:
                    run('sudo', a.home / '.zen-kernel/zen-kernel.sh', 'install-service')
                    run('sudo', a.home / '.zen-kernel/zen-kernel.sh', 'reapply', '--auto')
                if 'decky' in selected: run('sudo', 'systemctl', 'restart', 'plugin_loader'); loader_stopped = False
        finally:
            if loader_stopped: run('sudo', 'systemctl', 'start', 'plugin_loader')
    print('Restoration completed. Reboot, then run verify and perform the README hardware checks.')

def steam_root(a):
    candidate = a.home / '.steam/steam'
    root = candidate.resolve() if candidate.exists() else a.home / '.local/share/Steam'
    if not root.resolve().is_relative_to(a.home.resolve()):
        raise ValueError('Steam directory resolves outside the target home')
    return root

def enable_cef(a):
    root = steam_root(a)
    root.mkdir(parents=True, exist_ok=True)
    (root / '.cef-enable-remote-debugging').touch()

def verify(a, selected):
    missing = []
    for c in selected:
        required = paths(c)
        if c == 'decky': required = ['homebrew/services/PluginLoader', '/etc/systemd/system/plugin_loader.service']
        if c == 'homebrew': required = ['/home/linuxbrew/.linuxbrew/bin/brew']
        for p in required:
            if not source(a.home, a.root, p).exists(): missing.append(c + ': ' + p)
        if c in PLUGINS:
            for p in ['plugin.json', 'dist/index.js']:
                if not (a.home / 'homebrew/plugins' / PLUGINS[c] / p).is_file(): missing.append(c + ': ' + p)
        if not a.sandbox:
            for s in SERVICES.get(c, []): run('systemctl', 'is-enabled', '--quiet', s)
    if missing: raise ValueError('Missing installation files:\n' + '\n'.join(missing))
    if 'decky' in selected and not (steam_root(a) / '.cef-enable-remote-debugging').is_file():
        raise ValueError('Steam CEF debugging marker missing; rerun restore and reboot')
    if not a.sandbox and 'decky' in selected:
        try:
            with urllib.request.urlopen('http://127.0.0.1:8080/json', timeout=5) as response:
                tabs = json.load(response)
            if not isinstance(tabs, list) or not tabs:
                raise ValueError('Steam debugging endpoint has no tabs')
        except (OSError, ValueError, urllib.error.URLError) as e:
            raise ValueError('Steam CEF endpoint unavailable. Reboot into Gaming Mode after restore, then verify again.') from e
    if not a.sandbox:
        for c, service in [('decky', 'plugin_loader'), ('lg-tv', 'lg-tv-control-steam-button')]:
            if c in selected: run('systemctl', 'is-active', '--quiet', service)
        if 'drive-mount' in selected: run('findmnt', '--mountpoint', '/run/media/deck/2tb-external')
        if 'zen' in selected and 'zen' not in platform.release():
            raise ValueError('Zen is selected but not running; reboot and verify again')
    print('Installation checks passed. Functional hardware checks remain manual; see README.')

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['capture', 'plan', 'restore', 'verify'])
    p.add_argument('--backup', help='Private capture directory')
    p.add_argument('--output', help='New capture directory')
    profiles = p.add_mutually_exclusive_group()
    profiles.add_argument('--full', action='store_true', help='Select all components')
    profiles.add_argument('--minimal', action='store_true', help='Select default essentials (also the default)')
    profiles.add_argument('--components', help='Exact comma-separated component selection; dependencies added')
    p.add_argument('--enable', default='', help='Additional comma-separated components')
    p.add_argument('--disable', default='', help='Excluded comma-separated components')
    p.add_argument('--config', choices=['restore', 'defaults'], default='restore')
    p.add_argument('--stateless', action='store_true', help='Ignore backup entirely; use fresh installers')
    p.add_argument('--reset-config', action='store_true', help='Back up and remove selected existing configuration')
    p.add_argument('--sandbox', type=Path, help='Isolated test filesystem; no sudo, services, or installer execution')
    p.add_argument('--home', type=Path, help='Capture source home; live restores require /home/deck')
    a = p.parse_args(argv)
    a.root = a.sandbox.resolve() if a.sandbox else Path('/')
    a.home = a.home.resolve() if a.home else a.root / 'home/deck'
    if a.command == 'restore' and not a.sandbox and a.home != Path('/home/deck'):
        raise ValueError('Live restore target must be /home/deck')
    if a.sandbox and (a.root == Path('/') or not a.home.is_relative_to(a.root)):
        raise ValueError('Sandbox must contain the target home and cannot be /')
    if a.reset_config and not (a.stateless or a.config == 'defaults'):
        raise ValueError('--reset-config requires defaults/stateless mode')
    os.umask(0o077)
    selected = selection(a)
    specs = json.loads((BASE / 'installers.json').read_text())
    print('Components:', ', '.join(selected) or '(none)', flush=True)
    if a.command == 'capture': return capture(a, selected)
    if a.command == 'verify': return verify(a, selected)
    payload = bundle(a, selected)
    if a.command == 'plan':
        for c in selected:
            origin = 'captured software' if 'software' in payload.get(c, {}) else 'pinned upstream installer' if c in specs else 'UNAVAILABLE: capture required'
            print(c + ': ' + origin + '; ' + ('restore saved settings' if 'config' in payload.get(c, {}) else 'preserve existing / fresh defaults'))
        return
    restore(a, selected, payload, specs)

if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, subprocess.CalledProcessError, zipfile.BadZipFile, urllib.error.URLError) as e:
        print('ERROR:', e, file=sys.stderr); sys.exit(1)
