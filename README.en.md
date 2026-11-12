# NeteaseVault

[简体中文](README.md) | **English**

[![Release](https://img.shields.io/github/v/release/LISparrowC1/NeteaseVault?style=for-the-badge)](https://github.com/LISparrowC1/NeteaseVault/releases)
[![License](https://img.shields.io/badge/License-MIT-3b7a6e?style=for-the-badge)](LICENSE)
[![Windows](https://img.shields.io/badge/Windows-10%2F11-0078D4?style=for-the-badge&logo=windows)](https://github.com/LISparrowC1/NeteaseVault/releases)

Current version: **1.2.9**

An archive tool for NetEase Cloud Music "Liked Songs": sync the playlist, resolve
downloads through several engines, verify the files strictly, and keep a local
library that stays playable.

It is not an online streaming client. The point is to keep your liked songs in a
local library with known order, verified sources, real lossless detection, clean
tags, and an atomic move into place.

---

## ✨ Features

| Feature | What it does |
| --- | --- |
| Playlist sync | Imports the whole Liked Songs playlist with order, duration, cloud quality and playability |
| Seven views | Playlist, unliked, unavailable, waiting, review, failed, downloaded |
| Multiple engines | musicdl, custom LX sources, official API; the configured channel order is respected |
| Strict matching | Same `song_id` is authoritative; search candidates need normalized title/artist/album equality, whole-second duration equality, and uniqueness |
| Fake-lossless detection | Decodes PCM and checks spectral cutoff, bitrate and high-band cliffs; grey cases go to manual review |
| Atomic publish | Downloads into staging, validates, then moves into the library |
| Tag cleanup | Fixed `Title - Artist.ext` naming and a four-field tag whitelist |
| Custom sources | Manual import, auto-fetch, health check, manual order, auto-order by test result |
| Player | Lyrics and full-track spectrum; a live up/down mirrored spectrum sits below the left switch on the spectrum page |
| Local first | Cookie encrypted with Windows DPAPI; no registry, AppData, telemetry or listening data uploads |
| Green install | The installed folder is movable; delete it to uninstall; caches can be cleared individually |

---

## 🚀 Quick start

### 1. Install

Download the latest installer from [Releases](https://github.com/LISparrowC1/NeteaseVault/releases):

```text
NeteaseVault-<version>-Setup.exe
```

It installs to `current-directory\NeteaseVault` by default and creates:

```text
NeteaseVault.exe
data/
music/
```

Move the whole folder freely; deleting it uninstalls the app.

### 2. Log in

QR login is disabled by NetEase (error 8821). Use a cookie:

1. Sign in at [music.163.com](https://music.163.com).
2. Press `F12` -> `Application` -> `Cookies`.
3. Copy the value of `MUSIC_U` for `music.163.com`.
4. Paste it into the NeteaseVault login dialog.

The cookie is stored in `data/credentials.bin`, encrypted with the current Windows
user's DPAPI.

### 3. Sync

Click **Sync**. The app reads the account, finds Liked Songs, loads its order and
track details, and stores the result in `data/library.db`. The first sync is slower;
later syncs update changes only.

### 4. Download

Select tracks in **Waiting** and click **Download selected**.

The channel order comes from **Settings -> Download -> Channel order**, for example:

```text
musicdl
custom source
official API
```

Custom sources run at the position configured there; they are never forced ahead
of musicdl or the official API.

### 5. Custom sources

Open **Settings -> Custom sources -> Open source manager**.

- **Manual import** copies any `.js` into `data/engine/scripts`; the engine reports
  whether it actually loads.
- **Auto fetch** downloads candidates from the configured public repositories,
  validates them, tests them with a real cloud song, and installs only working ones.
- **Health check** uses the first not-yet-downloaded song from Liked Songs; if all
  are downloaded, it uses the first song.

Ordering:

- **Move up / Move down** changes the order and saves it immediately.
- **Sort by test result** puts successful sources first, then untested, then failed,
  ordered by latency.
- **Sort after check** reorders automatically when the health check finishes.

If a source fails to resolve or download, the next one is tried; only after all
custom sources fail does the next download channel run.

The repository list is editable at:

```text
data/source_repos.json
```

### 6. Player and spectrum

Double-click a downloaded track:

- left: cover, title, artist/album, Lyrics/Spectrum switch;
- right: lyrics, or the full-track static spectrum;
- on the Spectrum page, a 300x55 live spectrum appears below the left switch, mirrored
  around a horizontal axis, with tight dark 50%-opacity bars.

The static spectrum uses Spek's default SoX palette (0 to -120 dB) and is never cached.

---

## 📁 Layout

```text
NeteaseVault.exe
data/     runtime, engine, certificates, database, credentials, config, logs, cache, staging, sources
music/    library
```

- `music/`: final tracks, named `Title - Artist.ext`.
- `data/library.db`: playlist, local state, approvals, sync history.
- `data/credentials.bin`: DPAPI-encrypted cookie.
- `data/engine/scripts/`: manually imported source scripts.
- `data/engine/scripts/auto-*.js`: auto-fetched working sources; clearable from settings.
- `data/source_repos.json`: editable repository list.
- `data/cache/covers/`: cover cache.
- `data/staging/`: download staging.
- `data/tmp/`: temporary files, including auto-fetch work directories.

All runtime writes except `music/` stay under `data/`; no registry or `%AppData%`.

---

## 🧠 How it works

### Sync

Cloud and local state are independent axes:

- cloud: `cloud_present`, `cloud_playable`, order, duration, quality;
- local: `local_state`, `local_rel_path`, format, actual duration.

Sync updates cloud information without overwriting local download state. A song
removed from the cloud while still on disk goes to **Unliked**; its file is not
deleted automatically.

### Download pipeline

```text
resolve candidates -> match -> download -> duration check -> fake-lossless check
-> tag cleanup -> atomic publish
```

1. **Resolve** channels in the configured order and collect candidate URLs.
2. **Match** prefers the same `song_id`; search candidates need strict matching.
3. **Download** into `data/staging/<song_id>/`.
4. **Duration check** rejects files whose actual duration differs from the cloud.
5. **Fake-lossless check** decodes PCM and examines cutoff, bitrate and high-band
   cliffs; grey cases go to manual review.
6. **Tag cleanup** keeps only the necessary fields.
7. **Publish** moves the file into `music/` atomically and updates the database.

Failed attempts leave no partial file. If a candidate fails, the next candidate from
the same channel is tried; a channel is skipped only after its candidates fail.

### Matching

- Same `song_id` from official/custom sources is treated as the same track.
- Search results must match normalized title, artist and album exactly, with
  whole-second duration equality and a unique candidate.
- Anything else goes to manual review instead of guessing.

### Fake lossless

Extension and bitrate alone are not enough. The program decodes real PCM, runs an
FFT, checks high-frequency cutoff and cliffs, and combines that with bitrate. Clear
failures are rejected; ambiguous cases go to review. A 320k target does not use the
lossless gate.

### Custom sources

LX sources use `globalThis.lx`: a script turns a song ID into a playable URL.
Auto-fetch:

1. discovers scripts from `data/source_repos.json`;
2. checks for `@name`, `sources` and LX initialization;
3. writes them to a temporary directory;
4. resolves the first not-yet-downloaded cloud song with each candidate;
5. copies only successful scripts as `auto-*.js`;
6. tries them in the saved order on later downloads.

Third-party sources can disappear at any time; health checks and fallback are there
for that reason.

### Spectrum

- Static: the whole-track spectrum is generated in the background and never cached.
- Live: runs only on the spectrum page, reading a small PCM window around the
  current position; it stops immediately when the page is left.

---

## 🛠️ Build

Windows + Python 3.14:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
pwsh -NoProfile -File build\build.ps1
```

The build produces a onedir program with PyInstaller, runs `--selftest`, packs it as
an installer resource, compiles the green installer with `csc.exe`, and writes the
installer to `release\` next to the repository.

Custom sources need `runtime\node.exe`. Only source-built artifacts are shipped.

---

## 🧹 Cache and moving

Settings -> Cache can clear:

| Item | Path |
| --- | --- |
| Cover cache | `data/cache/covers` |
| Download staging | configured staging path |
| Temporary files | `data/tmp` |
| musicdl output | `data/musicdl_outputs` |
| Auto-fetched sources | `data/engine/scripts/auto-*.js` |

Clear all does not touch the library, database, credentials or configuration.

To move the app: quit it, move the whole `NeteaseVault` directory, and start it
again. Do not move only `NeteaseVault.exe`.

---

## ❓ Troubleshooting

**Sync fails or hangs**  
Check cookie expiry and network access; force-closing during sync can interrupt DB writes.

**Downloads always fail**  
Check the failure/review reason, channel order, source health and network.

**Auto-fetch finds nothing working**  
Third-party sources expire. Add repositories in `data/source_repos.json`, import a
working script manually, then run health checks again.

**A `.js` import does not show up**  
Check the load error in the source table; not every `.js` is an LX source.

**Covers do not update / cache is large**  
Clear cover cache in settings and reopen the player page.

**Uninstall**  
Quit and delete the install folder. No registry, service or AppData leftovers.

---

## ⚠️ Limitations

- Windows 10/11 only.
- Depends on NetEase APIs and third-party sources; API changes or dead sources can
  cause failures.
- Fake-lossless detection is heuristic, not a 100% guarantee; grey cases are manual.
- Auto-fetched sources come from public third-party repositories and are not
  guaranteed by this project.
- This project provides no music content; it only archives and manages local files.
- Only archive content you have the right to keep.

---

## 📄 License

MIT, see [LICENSE](LICENSE).
