# NeteaseVault

网易云音乐「我喜欢的音乐」归档工具：同步歌单 → 多源下载 → 严格校验 → 本地长期保存。

## 功能

- 同步「我喜欢的音乐」全部曲目，记录顺序、时长、云端音质与可播状态
- 多引擎下载：musicdl、自定义源脚本、官方接口，顺序可调
- 严格匹配：同一 `song_id` 的官方/自定义源候选直接视为同一首；搜索候选要求歌名/歌手/专辑归一化后完全相等、时长整秒相等且候选唯一，否则转人工
- 假无损检测：入库前解码 PCM，按频谱截止、码率与高频断崖判断，灰区转人工
- 暂存区校验后原子入库，文件名固定为 `歌名 - 歌手.ext`，标签只保留四项
- 七个视图：网易歌单、已取消喜欢、失效、等待下载、待确认、匹配失败、已下载
- 内置播放器；播放页可切换歌词/整首频谱，频谱页左栏选项下方显示上下镜像实时频谱
- Cookie 登录，凭证用 Windows DPAPI 加密
- 绿色安装包：安装后整个目录可移动，删除目录即卸载，不写注册表/AppData

## 构建

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
pwsh -NoProfile -File build\build.ps1
```

构建从源码生成 onedir 程序，再编译绿色安装器；最终安装包写入上一级 `release\`。
自定义源需要 `runtime\node.exe`。

## 安装与运行

双击 `NeteaseVault-<版本号>-Setup.exe`，选择安装目录（默认“当前目录\NeteaseVault”）。
安装后目录结构：

```
NeteaseVault.exe
data/          运行库、引擎、证书、数据库、凭证、日志、缓存、暂存、自定义源脚本
music/         音乐库
```

除了 `music/`，运行期写入都在 `data/`；目录可整体搬走。删除整个目录即卸载。

## 登录

扫码登录已被网易关闭（8821），使用 Cookie：登录 music.163.com 后按 F12 →
Application → Cookies → 复制 `MUSIC_U`，粘贴到登录窗口即可。

## 许可

MIT

---

# NeteaseVault (English)

Archive tool for NetEase Cloud Music "Liked Songs": sync the playlist, download tracks,
validate them strictly and keep a local library that stays playable.

## Features

- Syncs the whole playlist with order, duration, quality and playability
- Multiple download engines (musicdl, custom source scripts, official API)
- A single matching `song_id` from the official/custom-source channels is authoritative;
  search candidates must pass normalized title/artist/album equality, whole-second
  duration equality, and be unique, otherwise they go to manual review
- Fake-lossless detection decodes PCM before tagging and checks spectral cutoff,
  bitrate and high-band cliffs; grey cases go to manual review
- Staging area, validation, atomic move into the library
- Fixed naming (`Title - Artist.ext`) and a four-field tag whitelist
- Seven views: playlist, unliked, unavailable, waiting, review, failed, downloaded
- Built-in player with lyrics and a full-track spectrum view; the spectrum page shows
  a compact up/down mirrored live spectrum below the left-side switch
- Cookie login, credentials encrypted with Windows DPAPI
- Green installer: the installed folder is movable and deleting it uninstalls the app;
  no registry or AppData writes

## Build

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
pwsh -NoProfile -File build\build.ps1
```

The build produces an onedir program from source and compiles the green installer;
the final installer is written to the parent `release\` folder.
Custom sources require `runtime\node.exe`.

## Install and run

Run `NeteaseVault-<version>-Setup.exe`, choose an install directory (default:
`current-directory\NeteaseVault`). The installed layout is:

```
NeteaseVault.exe
data/          runtime, engine, certificates, database, credentials, logs, cache, staging, custom sources
music/         library
```

Apart from `music/`, runtime writes stay in `data/`. The whole folder can be moved;
delete it to uninstall.

## Login

QR login was disabled by NetEase (error 8821). Use a cookie: sign in at music.163.com,
open F12 -> Application -> Cookies, copy `MUSIC_U` and paste it into the login dialog.

## License

MIT
