# NeteaseVault

网易云音乐「我喜欢的音乐」归档工具：同步歌单 → 多源下载 → 严格校验 → 本地长期保存。

## 功能

- 同步「我喜欢的音乐」全部曲目，记录顺序、时长、云端音质与可播状态
- 多引擎下载：musicdl、自定义源脚本、官方接口，顺序可调
- 严格匹配：歌名/歌手/专辑归一化后完全相等、时长整秒相等、候选唯一，否则转人工确认
- 假无损检测：按 18–22 kHz 高频能量判断，可疑文件转人工
- 暂存区校验后原子入库，文件名固定为 `歌名 - 歌手.ext`，标签只保留四项
- 七个视图：网易歌单、已取消喜欢、失效、等待下载、待确认、匹配失败、已下载
- 内置播放器，整页歌词随播放位置滚动，独立播放队列
- Cookie 登录，凭证用 Windows DPAPI 加密

## 构建

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
pwsh -NoProfile -File build\build.ps1
```

产物是项目根目录的单文件 exe。自定义源需要 `runtime\node.exe`。

## 首次运行

程序在自己的同级目录创建所需文件夹，不写系统目录：

```
NeteaseVault.exe
music/     音乐库
data/      数据库、凭证、日志、缓存、暂存
```

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
- Strict matching: normalized title/artist/album equality, whole-second duration,
  unique candidate only, otherwise manual review
- Fake-lossless detection via high-band energy
- Staging area, validation, atomic move into the library
- Fixed naming (`Title - Artist.ext`) and a four-field tag whitelist
- Seven views: playlist, unliked, unavailable, waiting, review, failed, downloaded
- Built-in player with a full-page scrolling lyrics view and a play queue
- Cookie login, credentials encrypted with Windows DPAPI

## Build

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
pwsh -NoProfile -File build\build.ps1
```

A single executable is written to the project root. Custom sources require
`runtime\node.exe`.

## First run

The executable creates what it needs next to itself:

```
NeteaseVault.exe
music/     library
data/      database, credentials, logs, cache, staging
```

## Login

QR login was disabled by NetEase (error 8821). Use a cookie: sign in at music.163.com,
open F12 -> Application -> Cookies, copy `MUSIC_U` and paste it into the login dialog.

## License

MIT
