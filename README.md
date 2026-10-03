# SteamOS utility recovery

Selective recovery of the utilities on this SteamOS machine. Defaults install Homebrew,
Decky, Decktation, CSS Loader, and Steamcord. Games, saves, Proton prefixes, personal
files, desktop preferences, SSH/AWS keys, and development repositories are outside scope.

The entry point is Bash; the implementation uses **system Python 3.9+**, with no pip
packages. Keep `deck-recovery.sh`, `recovery.py`, and `installers.json` together.
A Git snippet can hold these files, but the Bash file alone is not standalone.

## Quick start: utilities with default settings

Run in Desktop Mode as `deck`, with networking and a working sudo password:

```bash
cd /home/deck/projects/deck-recovery
./deck-recovery.sh plan --stateless --components css-loader,steamcord
./deck-recovery.sh restore --stateless --components css-loader,steamcord
./deck-recovery.sh verify --components css-loader,steamcord
```

Dependencies automatically add Decky and Homebrew. To include Decktation too, omit
`--components`. Steamcord needs a fresh login. Its bundled integration can request
additional software such as Vesktop; this tool does not preserve Discord sessions.

On a freshly reimaged machine these plugins start with defaults. On an existing
installation stateless mode preserves settings. Add `--reset-config` to back up and
remove the selected components' known settings, data, CSS themes, and loader settings.
This does not clear Steam/CEF or Vesktop authentication stores. Log out separately if
removing an existing account session is your goal.

## Capture now, restore after recovery

Capture does not stop services. Exit Steam/Decky and other relevant utilities for a
consistent final capture; a capture taken while they are running is a rehearsal.

```bash
./deck-recovery.sh capture --output /path/to/external-storage/essentials-2026-10-02
# Optional components must be captured if you want to recover them later.
sudo -v
./deck-recovery.sh capture --full --output /path/to/external-storage/full-2026-10-02
```

LG TV configuration can require sudo read access. If cached authorization is unavailable,
capture fails with an actionable error. Alternatively run `sudo ./deck-recovery.sh capture
--full --output ...`; files are returned to the invoking user's ownership. Never run
live `restore` as root. An unsuccessful capture leaves a partial directory without a
valid manifest; choose a new output directory for the retry.

**Capture directories contain private configuration in plaintext.** They are created
with mode 0700. Encrypt the entire directory with your preferred backup tool before
uploading or storing elsewhere; keep the decryption key off this machine. Hashes detect
corruption, not malicious edits to both the manifest and archive. Only restore trusted
bundles. Capture rejects symlinks rather than silently dereferencing them.

After reimaging, complete SteamOS first-run setup, networking, and `passwd`, enter Desktop
Mode, recover this project and your decrypted backup, then:

```bash
./deck-recovery.sh plan --backup /path/to/essentials
./deck-recovery.sh restore --backup /path/to/essentials
# Reboot, then:
./deck-recovery.sh verify
```

For selected extras:

```bash
./deck-recovery.sh restore --backup /path/to/full --enable lg-tv,drive-mount,deckshots
./deck-recovery.sh verify --enable lg-tv,drive-mount,deckshots
```

Use the same component flags for `plan`, `restore`, and `verify`. Disabled components are
left untouched; flags do not uninstall existing software. Disconnect the external Steam
library during reimaging and reconnect it before selecting `drive-mount`. The script never
partitions or formats disks.

## Components

| Name | Default | Contents |
| --- | --- | --- |
| `homebrew` | On | Homebrew installation; no formula/cask inventory replay |
| `decky` | On | Loader binary, service, loader preferences |
| `decktation` | On | Plugin and its settings/data |
| `css-loader` | On | Plugin, settings/data, CSS themes |
| `steamcord` | On | Plugin, settings/data, known Steamcord JSON preferences |
| `deckshots` | Off | Plugin and settings/data |
| `pause-games` | Off | Plugin and settings/data |
| `web-browser` | Off | Plugin and settings/data |
| `volume-mixer` | Off | Plugin and settings/data |
| `audio-loader` | Off | Plugin, settings/data, sound packs |
| `volume-boost` | Off | Plugin and settings/data |
| `lg-tv` | Off | Installed binary, two services, environment file, pairing key |
| `drive-mount` | Off | Existing UUID-based mount service and keep list |
| `zen` | Off | Installed Zen script, services, keep list; reapply on restore |

Debug LG services remain outside scope. The optional drive component currently targets
UUID `5d5c2fea-90d4-4ed5-bbbf-0194853ae1c2` and `/run/media/deck/2tb-external`.
A missing drive fails restoration before target changes. This is intentionally specific
to this machine; edit the captured service and code check together to support another drive.

## Commands and parameters

| Parameter | Meaning |
| --- | --- |
| `capture` | Write selected installed software/configuration ZIPs and a hash manifest |
| `plan` | Validate bundle hashes and print resolved components and sources; no target changes |
| `restore` | Stage downloads/archives, install selected components, restore settings if requested |
| `verify` | Check installed files/plugin layouts, service enablement, live Decky/LG listener activity, drive mount, and running Zen kernel |
| `--output PATH` | Required new directory for capture; existing directories are refused |
| `--backup PATH` | Decrypted capture directory for restoration |
| `--minimal` | Default essential profile |
| `--full` | All components |
| `--components LIST` | Exact comma-separated selection; replaces profile; dependencies added |
| `--enable LIST` | Add components to selection |
| `--disable LIST` | Remove components; disabling a required dependency is an error |
| `--config restore` | Default: restore captured software and configuration; requires backup |
| `--config defaults` | Skip saved configuration; optionally use only software from `--backup` |
| `--stateless` | Ignore backup entirely and use built-in pinned upstream installers |
| `--reset-config` | With defaults/stateless only: save and remove known selected configuration |
| `--sandbox PATH` | Isolated filesystem for testing; no sudo, services, or Homebrew/Zen execution |
| `--home PATH` | Alternate capture source; sandbox target home must stay inside sandbox |
| `--help` | Show command-line help |

`--minimal`, `--full`, and `--components` are mutually exclusive. Enable/disable flags
apply afterward; disable wins. Plugins require Decky, and Decky requires Homebrew.
An empty exact selection (`--components ''`) selects nothing.

Stateless downloads support the essentials: Decky 3.2.6, Decktation 0.3.11-exp14,
CSS Loader 2.1.2, Steamcord 1.30.0, and a commit-pinned Homebrew bootstrap. SHA-256 values
are in `installers.json`; there are no `latest` release URLs. Homebrew's bootstrap itself
is pinned, but the Homebrew checkout it installs can evolve.

Optional components use captured artifacts rather than unverified fresh downloads.
For optional utilities without their saved configuration:

```bash
./deck-recovery.sh restore --full --config defaults --backup /path/to/full
```

LG TV needs environment/pairing configuration to work, so use configuration restoration
for that component. `--stateless --full` fails before installation because optional fresh
installers are not supplied. Fresh downloads need networking; an essentials bundle can
restore artifacts offline if Homebrew is already installed. Homebrew installation needs
networking and prerequisites handled by its official installer.

## Replacement backups, failures, and updates

Existing managed paths are saved under `~/.local/state/deck-recovery/*-replacements/`
before replacement. The directory is private. No completed-stage cache is trusted:
rerunning safely reapplies selected artifacts, and generates a new replacement backup.
Installations are staged before writes, but a live multi-component restore is not one
atomic transaction. A later command failure can leave earlier components installed.
Fix the cause and rerun. The loader is restarted on failure if it was previously running.

Custom units get narrow SteamOS atomic-update keep lists. Do not copy the entire old
`/etc`, package database, or boot partition onto a new SteamOS image. This tool does not
unlock the root filesystem globally; if a future SteamOS build rejects `/etc` writes,
resolve that compatibility issue before continuing.

Zen invokes the captured script's `install-service` and `reapply --auto`. It does **not**
guarantee reinstalling the exact old kernel package: the captured script resolves packages
for the installed SteamOS build. First confirm stock SteamOS works, inspect the script,
and retain recovery media/a way to boot stock before opting in. Do not assume an old
kernel integrates safely with a future image.

## Testing and acceptance

```bash
/usr/bin/python3 -m unittest discover -s tests -v
bash -n deck-recovery.sh
./deck-recovery.sh restore --backup /path/to/bundle --sandbox /tmp/recovery-rehearsal
./deck-recovery.sh verify --sandbox /tmp/recovery-rehearsal
```

Automated tests cover selection/dependencies, capture/restore/reruns, corrupt hashes,
ZIP traversal/symlinks, stateless backup isolation, selected resets, and unsupported
installer failure. Fixture tests use checked upstream CSS/Steamcord ZIPs under `assets/`.
Real essentials and optional-component captures (excluding privileged LG configuration) were also restored and verified in isolated filesystems. LG file restoration is covered with fixtures. A full LG capture still needs an interactive sudo session.
A stateless CSS Loader + Steamcord rehearsal also downloaded the actual pinned Decky and plugin releases, checked their hashes, installed them in an isolated filesystem, and passed verification. All 16 automated tests pass. Decky installation also creates Steam’s `.cef-enable-remote-debugging` marker; reboot into Gaming Mode before verification. Live verification checks that the local CEF debugging endpoint responds with tabs. A regression test also checks that live home directory ownership/access is repaired before inspecting files, including directories left by an interrupted fresh installation. Sandbox Homebrew is only a marker and does not prove the live installer works.

Live destructive recovery has not been rehearsed on a spare disk. After a real restore,
check Decky in Gaming Mode; open each selected plugin; check CSS themes; log in to
Steamcord; exercise dictation and controller bindings. If selected, check screenshots,
TV Steam-button behavior and suspend/resume, external-library availability after reboot,
and Zen boot/suspend with a stock fallback. `verify` is installation verification,
not a claim that these hardware/UI checks passed.

## Repository and backup layout

The project is a local Git repository. No remote is created or published automatically.
Private capture bundles belong outside this repository; `.gitignore` excludes common
backup locations and archives, but is not a secret scanner. `assets/` contains only the
unaltered public upstream CSS/Steamcord release ZIPs for tests; their upstream licenses
remain applicable. Runtime installation downloads and checksums pinned URLs, not these
fixture files.

## Decky frontend diagnostics

If the loader service is running but the Decky tab is missing, stay in Gaming Mode
and run these commands over SSH (or from a terminal):

```bash
./decky-diagnostics.sh
# If journal access is denied or incomplete:
./decky-diagnostics.sh --sudo --minutes 10
```

This read-only script collects service status, up to 200 recent journal lines,
Steam CEF tab titles, the Decky HTTP endpoint status, and the last 80 matching
browser errors from the final 4 MiB of `cef_log.txt`. It changes no settings and
restarts no services. `--minutes` accepts 1–1440 (default 10); `--sudo` applies only
to journal collection. Keep `decky_diagnostics.py` alongside the wrapper.

Authentication/plugin-event payloads are filtered, and browser tab URLs are omitted.
Filtering is best effort: review the output before sharing. A 404 from Decky's root
HTTP route still establishes that a server responded; it does not prove frontend
injection. Missing logs/endpoints are reported without stopping the remaining checks.
