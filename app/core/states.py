"""Track lifecycle.

Two independent axes, never mixed:

* cloud  -- is the song in "我喜欢的音乐" right now, and is it playable
* local  -- what has the downloader achieved for it

Every UI list is a filter over these, so a song leaving and re-entering the cloud
list never destroys its local state.
"""
from __future__ import annotations

# -- local state ---------------------------------------------------------

NONE = "none"                     # 等待下载（本地没有文件）
DOWNLOADED = "downloaded"         # 已下载
PENDING_REVIEW = "pending_review" # 待确认
MATCH_FAILED = "match_failed"     # 匹配失败

LOCAL_STATES = (NONE, DOWNLOADED, PENDING_REVIEW, MATCH_FAILED)

LOCAL_LABELS = {
    NONE: "等待下载",
    DOWNLOADED: "已下载",
    PENDING_REVIEW: "待确认",
    MATCH_FAILED: "匹配失败",
}

# -- list keys used by the sidebar ---------------------------------------

LIST_ALL = "all"                    # 网易歌单
LIST_REMOVED = "removed"            # 已取消喜欢
LIST_WAITING = "waiting"            # 等待下载
LIST_REVIEW = "review"              # 待确认
LIST_DOWNLOADED = "downloaded"      # 已下载
LIST_INVALID = "invalid"            # 失效
LIST_FAILED = "failed"              # 匹配失败

LISTS = (LIST_ALL, LIST_REMOVED, LIST_INVALID, LIST_WAITING,
         LIST_REVIEW, LIST_FAILED, LIST_DOWNLOADED)

LIST_LABELS = {
    LIST_ALL: "网易歌单",
    LIST_REMOVED: "已取消喜欢",
    LIST_WAITING: "等待下载",
    LIST_REVIEW: "待确认",
    LIST_DOWNLOADED: "已下载",
    LIST_INVALID: "失效",
    LIST_FAILED: "匹配失败",
}

LIST_TITLES = {
    LIST_ALL: "我喜欢的音乐",
    LIST_REMOVED: "已取消喜欢",
    LIST_WAITING: "等待下载",
    LIST_REVIEW: "待确认",
    LIST_DOWNLOADED: "已下载",
    LIST_INVALID: "失效",
    LIST_FAILED: "匹配失败",
}

# SQL predicate for each list; one source of truth for UI and exporters.
# 「网易歌单」is a *cloud view*: it only ever shows what the cloud currently has.
# Local files without cloud metadata carry `local_only = 1` and live in 已下载, where
# they are rendered with a 「本地」 tag. They never appear in the cloud view.
LIST_SQL = {
    LIST_ALL: "cloud_present = 1",
    LIST_REMOVED: "cloud_present = 0 AND local_only = 0",
    LIST_WAITING: "cloud_present = 1 AND cloud_playable = 1 AND local_state = 'none'",
    LIST_REVIEW: "cloud_present = 1 AND local_state = 'pending_review'",
    LIST_DOWNLOADED: "local_state = 'downloaded'",
    LIST_INVALID: "cloud_present = 1 AND cloud_playable = 0",
    LIST_FAILED: "cloud_present = 1 AND local_state = 'match_failed'",
}

# Lists that represent a cloud view rather than a local work queue.
CLOUD_VIEW_LISTS = (LIST_ALL, LIST_REMOVED, LIST_INVALID)
