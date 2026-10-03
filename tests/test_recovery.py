import argparse
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import recovery as r

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def invoke(self, *args):
        with contextlib.redirect_stdout(io.StringIO()):
            r.main(list(args))
    def fixture(self, root):
        home = root / 'home/deck'
        for name in ['SDH-CssLoader', 'Steamcord']:
            p = home / 'homebrew/plugins' / name
            (p / 'dist').mkdir(parents=True)
            (p / 'plugin.json').write_text('{}')
            (p / 'dist/index.js').write_text('working build')
            p = home / 'homebrew/settings' / name
            p.mkdir(parents=True)
            (p / 'settings.json').write_text('{"custom":true}')
        return home
    def test_selection_dependencies(self):
        a = argparse.Namespace(components='css-loader,steamcord', full=False, enable='', disable='')
        self.assertEqual(r.selection(a), ['homebrew', 'decky', 'css-loader', 'steamcord'])
        a.disable = 'decky'
        with self.assertRaises(ValueError): r.selection(a)
    def test_unknown_component(self):
        with self.assertRaises(ValueError): self.invoke('plan', '--stateless', '--components', 'oops')
    def test_capture_restore_and_rerun(self):
        src = self.root / 'source'; self.fixture(src)
        backup = self.root / 'bundle'
        self.invoke('capture', '--sandbox', str(src), '--components', 'css-loader,steamcord', '--output', str(backup))
        # Add a fake loader to avoid a network download while testing restore.
        p = src / 'home/deck/homebrew/services'; p.mkdir(); (p / 'PluginLoader').write_text('binary'); (p / '.loader.version').write_text('v3.2.6')
        backup2 = self.root / 'bundle2'
        self.invoke('capture', '--sandbox', str(src), '--components', 'css-loader,steamcord', '--output', str(backup2))
        dst = self.root / 'target'
        for _ in range(2):
            self.invoke('restore', '--sandbox', str(dst), '--components', 'css-loader,steamcord', '--backup', str(backup2))
        self.invoke('verify', '--sandbox', str(dst), '--components', 'css-loader,steamcord')
        self.assertIn('custom', (dst / 'home/deck/homebrew/settings/Steamcord/settings.json').read_text())
        self.assertFalse((dst / 'home/deck/Pictures').exists())
    def test_corrupt_backup_rejected_before_writes(self):
        src = self.root / 'src'; self.fixture(src)
        backup = self.root / 'bundle'
        self.invoke('capture', '--sandbox', str(src), '--components', 'css-loader', '--output', str(backup))
        (backup / 'css-loader-software.zip').write_bytes(b'bad')
        dst = self.root / 'dst'
        with self.assertRaises(ValueError): self.invoke('restore', '--sandbox', str(dst), '--components', 'css-loader', '--backup', str(backup))
        self.assertFalse(dst.exists())
    def test_traversal_and_symlinks_rejected(self):
        p = self.root / 'bad.zip'
        with zipfile.ZipFile(p, 'w') as z: z.writestr('../escaped', 'bad')
        with self.assertRaises(ValueError): r.unpack(p, self.root / 'out')
        with zipfile.ZipFile(p, 'w') as z:
            i = zipfile.ZipInfo('link'); i.external_attr = 0o120777 << 16; z.writestr(i, '/etc')
        with self.assertRaises(ValueError): r.unpack(p, self.root / 'out')
    def test_stateless_never_reads_backup_and_preserves_settings(self):
        dst = self.root / 'target'; home = self.fixture(dst)
        assets = r.BASE / 'assets'
        def fake_fetch(spec, dest):
            key = 'css-loader' if 'CssLoader' in spec['url'] else 'steamcord' if 'Steamcord' in spec['url'] else None
            dest.write_bytes((assets / (key + '.zip')).read_bytes() if key else b'loader')
        with patch.object(r, 'fetch', fake_fetch):
            self.invoke('restore', '--sandbox', str(dst), '--components', 'css-loader,steamcord', '--stateless', '--backup', '/does/not/exist')
            self.invoke('verify', '--sandbox', str(dst), '--components', 'css-loader,steamcord')
        self.assertIn('custom', (home / 'homebrew/settings/Steamcord/settings.json').read_text())
        self.assertFalse((home / 'homebrew/plugins/decktation').exists())
    def test_explicit_reset_backs_up_selected_settings(self):
        dst = self.root / 'target'; home = self.fixture(dst)
        a = argparse.Namespace(home=home, root=dst, sandbox=dst)
        ins = r.Installer(a); ins.reset('steamcord')
        self.assertFalse((home / 'homebrew/settings/Steamcord').exists())
        self.assertTrue((home / 'homebrew/settings/SDH-CssLoader/settings.json').exists())
        self.assertTrue(list(ins.saved.rglob('settings.json')))
    def test_missing_optional_installer_fails_before_writes(self):
        dst = self.root / 'dst'
        with patch.object(r, 'fetch', lambda spec, dest: dest.write_bytes(b'loader')):
            with self.assertRaises(ValueError): self.invoke('restore', '--sandbox', str(dst), '--components', 'lg-tv', '--stateless')
        self.assertFalse((dst / 'home/deck/.local/bin/lg-tv-control').exists())
    def test_optional_system_components_roundtrip(self):
        src = self.root / 'src'
        home = src / 'home/deck'
        for c in ['lg-tv', 'drive-mount', 'zen']:
            for rel in r.paths(c) + r.paths(c, True):
                p = r.source(home, src, rel)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('fixture')
        backup = self.root / 'bundle'
        flags = ['--components', 'lg-tv,drive-mount,zen']
        self.invoke('capture', '--sandbox', str(src), '--output', str(backup), *flags)
        dst = self.root / 'dst'
        self.invoke('restore', '--sandbox', str(dst), '--backup', str(backup), *flags)
        self.invoke('verify', '--sandbox', str(dst), *flags)
        self.assertEqual((dst / 'home/deck/.lg_webos_key.json').read_text(), 'fixture')
        self.assertFalse((dst / 'home/deck/homebrew').exists())
    def test_defaults_ignores_corrupt_config_archive(self):
        src = self.root / 'src'; self.fixture(src)
        p = src / 'home/deck/homebrew/services'; p.mkdir()
        (p / 'PluginLoader').write_text('binary')
        backup = self.root / 'bundle'
        self.invoke('capture', '--sandbox', str(src), '--components', 'steamcord', '--output', str(backup))
        (backup / 'steamcord-config.zip').write_bytes(b'corrupt private config must not be read')
        dst = self.root / 'dst'
        self.invoke('restore', '--sandbox', str(dst), '--components', 'steamcord', '--backup', str(backup), '--config', 'defaults')
        self.assertFalse((dst / 'home/deck/homebrew/settings/Steamcord').exists())
    def test_symlink_target_ancestor_refused(self):
        dst = self.root / 'dst'; home = dst / 'home/deck'
        home.mkdir(parents=True)
        outside = self.root / 'outside'; outside.mkdir()
        (home / 'homebrew').symlink_to(outside, target_is_directory=True)
        a = argparse.Namespace(home=home, root=dst, sandbox=dst)
        src = self.root / 'file'; src.write_text('data')
        with self.assertRaises(ValueError): r.Installer(a).replace(src, home / 'homebrew/file')
        self.assertFalse((outside / 'file').exists())
    def test_live_home_ancestors_repaired_before_target_inspection(self):
        dst = self.root / 'dst'; home = dst / 'home/deck'; home.mkdir(parents=True)
        a = argparse.Namespace(home=home, root=dst, sandbox=None)
        src = self.root / 'version'; src.write_text('v3.2.6')
        target = home / 'homebrew/services/.loader.version'
        calls = []
        def record(*args): calls.append(tuple(str(x) for x in args))
        with patch.object(r, 'run', record), patch.object(r.subprocess, 'run', return_value=argparse.Namespace(returncode=1)):
            r.Installer(a).replace(src, target)
        for parent in [home / 'homebrew', home / 'homebrew/services']:
            self.assertIn(('sudo', 'chown', str(r.os.getuid()) + ':' + str(r.os.getgid()), str(parent)), calls)
            self.assertIn(('sudo', 'chmod', 'u+rwx', str(parent)), calls)
        self.assertLess(calls.index(('sudo', 'chmod', 'u+rwx', str(target.parent))), calls.index(('sudo', 'cp', '-a', str(src), str(target))))
    def test_cef_marker_created_for_fresh_and_symlinked_steam(self):
        root = self.root / 'target'; home = root / 'home/deck'
        a = argparse.Namespace(home=home, root=root, sandbox=root)
        r.enable_cef(a)
        marker = home / '.local/share/Steam/.cef-enable-remote-debugging'
        self.assertTrue(marker.is_file())
        (home / '.steam').mkdir()
        (home / '.steam/steam').symlink_to(home / '.local/share/Steam', target_is_directory=True)
        r.enable_cef(a)
        self.assertTrue(marker.is_file())
    def test_cef_refuses_external_steam_target(self):
        home = self.root / 'home'; (home / '.steam').mkdir(parents=True)
        outside = self.root / 'outside'; outside.mkdir()
        (home / '.steam/steam').symlink_to(outside, target_is_directory=True)
        a = argparse.Namespace(home=home, root=self.root, sandbox=self.root)
        with self.assertRaises(ValueError): r.enable_cef(a)
    def test_homebrew_bashrc_preserves_content_and_is_idempotent(self):
        home = self.root / 'home'; home.mkdir()
        bashrc = home / '.bashrc'; bashrc.write_text('export CUSTOM=value')
        a = argparse.Namespace(home=home)
        r.configure_brew_shell(a)
        r.configure_brew_shell(a)
        content = bashrc.read_text()
        self.assertIn('export CUSTOM=value\n', content)
        self.assertEqual(content.count('brew shellenv bash'), 1)
        backups = list((home / '.local/state/deck-recovery').glob('*-bashrc'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), 'export CUSTOM=value')
    def test_homebrew_existing_shell_setup_not_duplicated(self):
        home = self.root / 'home'; home.mkdir()
        content = 'eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv bash)"\n'
        (home / '.bashrc').write_text(content)
        r.configure_brew_shell(argparse.Namespace(home=home))
        self.assertEqual((home / '.bashrc').read_text(), content)
    def test_checksum_mismatch(self):
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'bad')):
            with self.assertRaises(ValueError): r.fetch({'url':'https://example.org/file', 'sha256':'wrong'}, self.root / 'download')
    def test_reset_requires_defaults(self):
        with self.assertRaises(ValueError): self.invoke('plan', '--reset-config')

if __name__ == '__main__': unittest.main()
