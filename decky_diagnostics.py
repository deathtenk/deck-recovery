#!/usr/bin/env python3
"""Read-only Decky frontend diagnostics. Review output before sharing."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.request

PATTERN = re.compile(r'decky|1337|uncaught|syntaxerror|typeerror|failed to fetch|permission denied', re.I)

def sanitize(text):
    output = []
    for line in text.splitlines():
        if re.search(r'Dropping message|qr_login|REMOTE_AUTH_QR|data:image|authorization|access_token|refresh_token|"token"', line, re.I):
            output.append('[Potential authentication/plugin payload omitted]')
        else:
            output.append(line[:2000])
    return '\n'.join(output)

def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=20)
        print(sanitize(result.stdout))
        if result.stderr: print(sanitize(result.stderr))
        if result.returncode: print('Command exit status:', result.returncode)
    except (OSError, subprocess.TimeoutExpired) as e:
        print('Check unavailable:', e)

def endpoint(url, contexts=False):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            print(url, 'HTTP', response.status)
            if contexts:
                data = json.loads(response.read(1024 * 1024))
                if not isinstance(data, list): print('Unexpected response: expected tab list'); return
                for tab in data:
                    # Titles only; URLs can contain private browsing information.
                    print('  Context:', sanitize(str(tab.get('title', '(untitled)'))))
                print('SharedJSContext present:', any(t.get('title') == 'SharedJSContext' for t in data))
    except urllib.error.HTTPError as e:
        print(url, 'HTTP', e.code, '(server responded; route may not exist)')
    except (OSError, ValueError, urllib.error.URLError) as e:
        print(url, 'FAILED:', e)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sudo', action='store_true', help='Use sudo for journal access (may ask for password)')
    parser.add_argument('--minutes', type=int, default=10, help='Recent service journal window, default 10 minutes')
    args = parser.parse_args()
    if args.minutes < 1 or args.minutes > 1440: parser.error('--minutes must be between 1 and 1440')
    if args.sudo:
        try:
            # Authenticate on the terminal before starting timed/captured checks.
            subprocess.run(['sudo', '-v'], check=True)
        except (OSError, subprocess.CalledProcessError):
            print('sudo authentication failed; collecting unprivileged logs instead.')
            args.sudo = False
    print('Decky diagnostics — read-only. Run while Steam is in Gaming Mode.')
    print('Output filtering is best effort; review before sharing.\n')
    print('=== Service status ===')
    command(['systemctl', 'status', 'plugin_loader', '--no-pager', '-l'])
    print('\n=== Recent service journal ===')
    command((['sudo', '-n'] if args.sudo else []) + ['journalctl', '-u', 'plugin_loader', '-b', '--since', str(args.minutes) + ' minutes ago', '-n', '200', '--no-pager', '-o', 'cat'])
    print('\n=== Steam CEF endpoint ===')
    endpoint('http://127.0.0.1:8080/json', contexts=True)
    print('\n=== Decky web endpoint ===')
    endpoint('http://127.0.0.1:1337/')
    print('\n=== Steam browser errors (last 80 matching lines) ===')
    home = Path.home()
    roots = [home / '.local/share/Steam', home / '.steam/steam']
    seen = set()
    found = False
    for root in roots:
        path = (root / 'logs/cef_log.txt').resolve()
        if path in seen: continue
        seen.add(path)
        if not path.exists(): continue
        found = True
        print('Log:', path)
        try:
            # Limit reads to the last 4 MiB on machines with huge browser logs.
            with path.open('rb') as f:
                f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 4 * 1024 * 1024))
                if size > 4 * 1024 * 1024: f.readline()
                lines = f.read().decode('utf-8', errors='replace').splitlines()
            matches = [line for line in lines if PATTERN.search(line)]
            print(sanitize('\n'.join(matches[-80:])) if matches else 'No matching errors in log tail.')
        except OSError as e: print('Cannot read log:', e)
    if not found: print('cef_log.txt not found at the standard Steam locations.')
    print('\nDiagnostics complete. Endpoint/service success does not establish that the Decky UI rendered.')

if __name__ == '__main__': main()
