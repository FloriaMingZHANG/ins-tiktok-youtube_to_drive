#!/usr/bin/env python3
"""
从 Google 表格读取一列视频链接、一列命名，
依次下载（支持 Instagram / TikTok / YouTube / YouTube Shorts / 小红书 等）并按命名上传到 Google Drive。
画质：bestvideo+bestaudio 合并，确保原画质或最高可用画质。
"""

import csv
import os
import re
import subprocess
import sys
from urllib.parse import urlparse
import tempfile
import time
import webbrowser
from pathlib import Path
from typing import List, Optional, Tuple

import httplib2
import gspread
from dotenv import load_dotenv
from gspread_formatting import cellFormat, color, format_cell_range
from google.oauth2.credentials import Credentials as OAuth2Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# 作用域：表格读写 + Drive 读写
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

load_dotenv()

# 确保 yt-dlp（venv Scripts）和 ffmpeg 在 PATH 中，无论从何处调用都能找到
_scripts_dir = str(Path(sys.executable).parent)
_ffmpeg_candidates = [
    # WinGet 安装路径
    str(Path.home() / "AppData/Local/Microsoft/WinGet/Links"),
    # Chocolatey / scoop 常见位置
    r"C:\ProgramData\chocolatey\bin",
    r"C:\tools\ffmpeg\bin",
]
_extra_paths = [_scripts_dir] + [p for p in _ffmpeg_candidates if Path(p).exists()]
os.environ["PATH"] = os.pathsep.join(_extra_paths) + os.pathsep + os.environ.get("PATH", "")

# YouTube JS 挑战解析：Node.js 已安装时自动启用 EJS 远程组件，解决"Sign in to confirm you're not a bot"
_node_exe = next(
    (p for p in [
        str(Path("C:/Program Files/nodejs/node.exe")),
        str(Path.home() / "AppData/Roaming/nvm/current/node.exe"),
    ] if Path(p).exists()),
    None,
)
# --js-runtimes 格式：node 或 node:/path/to/node.exe
_node_runtime = f"node:{_node_exe}" if _node_exe else "node"
_YT_JS_ARGS = ["--js-runtimes", _node_runtime, "--remote-components", "ejs:github"]

# 表格
SPREADSHEET_URL = os.getenv("SPREADSHEET_URL", "").strip()
SPREADSHEET_KEY = os.getenv("SPREADSHEET_KEY", "").strip()
SHEET_NAME = os.getenv("SHEET_NAME", "").strip()
URL_COLUMN = os.getenv("URL_COLUMN", "A").strip().upper()
NAME_COLUMN = os.getenv("NAME_COLUMN", "B").strip().upper()
HEADER_ROWS = int(os.getenv("HEADER_ROWS", "1"))
# 上传后把 Drive 链接写回这一列（留空则不写回）
RESULT_COLUMN = os.getenv("RESULT_COLUMN", "").strip().upper()
# 封面图 Drive 链接写回这一列（留空则不下载/不写回封面）
THUMBNAIL_COLUMN = os.getenv("THUMBNAIL_COLUMN", "").strip().upper()

# 飞书导出（main 只做本地导出）：封面原图与 links.csv 的列名，与 feishu.py / push_export_to_feishu 共用 .env
FEISHU_MATCH_FIELD = os.getenv("FEISHU_MATCH_FIELD", "").strip()
FEISHU_DRIVE_LINK_FIELD = os.getenv("FEISHU_DRIVE_LINK_FIELD", "").strip()
FEISHU_EXPORT_DIR = os.getenv("FEISHU_EXPORT_DIR", "").strip()
# 为 1/true/yes 时：不把封面上传 Drive、不写 Sheet 封面列，只把封面原图保存到上面导出目录（方便你直接复制到飞书）
SKIP_DRIVE_COVER = os.getenv("SKIP_DRIVE_COVER", "").strip().lower() in ("1", "true", "yes")
# 为 1/true/yes 时：每条视频处理完后直接调飞书 API 写入「封面」列和「Drive 链接」列，无需再手动跑 push_export_to_feishu.py
FEISHU_PUSH_DIRECT = os.getenv("FEISHU_PUSH_DIRECT", "").strip().lower() in ("1", "true", "yes")
# 飞书作为数据来源：视频链接列名（如 发布链接）；设置后从飞书读取待处理记录，替代 Google 表格
FEISHU_URL_FIELD = os.getenv("FEISHU_URL_FIELD", "").strip()
# 每次最多处理条数（默认 50）
FEISHU_MAX_BATCH = int(os.getenv("FEISHU_MAX_BATCH", "50").strip())
# 本次运行做哪一类：DO_VIDEO=1 下载并上传视频到 Drive、写回链接；DO_COVER=1 下载封面并导出到 FEISHU_EXPORT_DIR。可只开一个或两个都开
DO_VIDEO = os.getenv("DO_VIDEO", "1").strip().lower() not in ("0", "false", "no")
DO_COVER = os.getenv("DO_COVER", "1").strip().lower() not in ("0", "false", "no")

# Drive
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "").strip()

# 可选：cookies 文件（部分平台如 Ins/TikTok 需登录时使用）
COOKIES_FILE = os.getenv("COOKIES_FILE", "").strip()
# 可选：从浏览器读 cookies，如 "chrome" / "firefox" / "safari"，与 COOKIES_FILE 二选一
COOKIES_FROM_BROWSER = os.getenv("COOKIES_FROM_BROWSER", "").strip().lower()

# 凭证：服务账号（读表）+ 可选 OAuth（上传到「我的网盘」用 OAuth，否则服务账号无空间）
CREDENTIALS_PATH = os.getenv("CREDENTIALS_PATH", "credentials.json")
# OAuth 用：client_secret 与 token 路径；留空则 Drive 仍用服务账号（仅共享网盘/Shared Drive 有效）
CLIENT_SECRET_PATH = os.getenv("CLIENT_SECRET_PATH", "client_secret.json").strip()
TOKEN_PATH = os.getenv("TOKEN_PATH", "token.json").strip()

# 慢速网络：设为 1/true/yes 时自动使用更长超时和间隔；也可单独调下面四项
SLOW_NETWORK = os.getenv("SLOW_NETWORK", "").strip().lower() in ("1", "true", "yes")
SOCKET_TIMEOUT = int(os.getenv("SOCKET_TIMEOUT", "120" if SLOW_NETWORK else "60").strip())
DOWNLOAD_RETRIES = int(os.getenv("DOWNLOAD_RETRIES", "8" if SLOW_NETWORK else "5").strip())
DOWNLOAD_DELAY_SECONDS = float(os.getenv("DOWNLOAD_DELAY_SECONDS", "10" if SLOW_NETWORK else "5").strip())
DOWNLOAD_TIMEOUT = int(os.getenv("DOWNLOAD_TIMEOUT", "900" if SLOW_NETWORK else "600").strip())  # 单条总超时(秒)，慢速模式 15 分钟
DRIVE_HTTP_TIMEOUT = int(os.getenv("DRIVE_HTTP_TIMEOUT", "1200" if SLOW_NETWORK else "600").strip())

_YTDLP_NOISE_MARKERS = (
    "FutureWarning:",
    "NotOpenSSLWarning:",
    "Deprecated Feature:",
    "warnings.warn(",
    "/site-packages/urllib3/",
    "/site-packages/google/auth/",
    "/site-packages/google/oauth2/",
    "/site-packages/google/api_core/",
    "You are using a Python version",
    "You are using a non-supported Python",
)


def _sanitize_ytdlp_stderr(text: str) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    kept = [ln for ln in lines if ln.strip() and not any(m in ln for m in _YTDLP_NOISE_MARKERS)]
    out = "\n".join(kept).strip()
    return out if out else "\n".join(lines[-40:]).strip()


def _is_instagram_url(url: str) -> bool:
    """判断是否为 Instagram 链接（需登录才能下载）。"""
    if not url or not isinstance(url, str):
        return False
    u = url.strip().lower()
    return "instagram.com" in u or "instagr.am" in u


def _instagram_unsupported_url_hint(url: str) -> Optional[str]:
    """
    若为 Ins 主页、Reels 列表页等 yt-dlp 无法作为「单条视频」处理的 URL，返回简短说明；否则返回 None。
    """
    if not _is_instagram_url(url):
        return None
    try:
        path = (urlparse(url.strip()).path or "").strip("/")
    except Exception:
        return None
    parts = [p.lower() for p in path.split("/") if p]
    if not parts:
        return None
    if parts[0] == "stories":
        return "Instagram「快拍」无法用本脚本下载，请改用单条贴文链接（/p/短码）或 Reel（/reel/短码）。"
    # 单段路径视为用户主页，如 /nextlevel3dstudio
    if len(parts) == 1:
        return "Instagram「主页」无法下载单条视频；请打开具体贴文或 Reel，复制含 /p/ 或 /reel/ 的链接填入表格。"
    # …/用户名/reels/ 等列表页
    if parts[-1] == "reels":
        return "Instagram「Reels 列表」页（…/reels/）不支持；请点开单条 Reel，复制地址栏中含 /reel/短码 的链接。"
    if len(parts) == 2 and parts[1] in ("tagged", "followers", "following", "saved", "guide", "channel"):
        return "该链接不是单条贴文/Reel；请使用 /p/ 或 /reel/ 形式的单条链接。"
    return None


def _is_x_twitter_url(url: str) -> bool:
    """判断是否为 X (Twitter) 链接（需登录才能稳定下载高清）。"""
    if not url or not isinstance(url, str):
        return False
    u = url.strip().lower()
    return "x.com" in u or "twitter.com" in u


def _is_cookie_database_error(err: Optional[str]) -> bool:
    """是否为 Chrome/Edge 无法复制 cookie 数据库的报错（浏览器未关闭或进程未退出）。"""
    if not err:
        return False
    e = err.lower()
    return ("cookie" in e and ("chrome" in e or "could not copy" in e)) or "cookie database" in e


def _can_read_browser_cookies(browser: str) -> bool:
    """尝试用 yt-dlp 读取浏览器 cookie，成功返回 True，无法读取（如浏览器未关）返回 False。"""
    cmd = [
        "yt-dlp",
        "--cookies-from-browser", browser,
        "--skip-download",
        "--no-warnings",
        "--socket-timeout", "15",
        "https://www.example.com",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        err = (result.stderr or result.stdout or "").lower()
        return "could not copy" not in err and "cookie database" not in err
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _append_or_set_env(key: str, value: str, env_path: Optional[Path] = None) -> None:
    """在 .env 中设置 key=value：若已存在则替换该行，否则追加。"""
    env_path = env_path or Path(".env")
    if not env_path.is_file():
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(f"# Instagram/登录 配置（由脚本自动添加）\n{key}={value}\n")
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    prefix = key + "="
    new_line = f"{key}={value}"
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(prefix):
            lines[i] = new_line
            found = True
            break
    if not found:
        lines.append("")
        lines.append(f"# Instagram/登录 配置（由脚本自动添加）")
        lines.append(new_line)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_login_if_needed(data: List[Tuple[str, str, int]]) -> None:
    """
    若待处理列表中有 Instagram 或 X (Twitter) 链接且未配置 cookies，则：
    1. 打开浏览器让用户登录相应站点
    2. 选择从哪个浏览器读取登录状态（或指定 cookies 文件）
    3. 写入 .env，之后运行自动使用，一劳永逸
    """
    global COOKIES_FILE, COOKIES_FROM_BROWSER
    urls = [url for url, _, _ in data]
    has_ig = any(_is_instagram_url(u) for u in urls)
    has_x = any(_is_x_twitter_url(u) for u in urls)
    if not has_ig and not has_x:
        return
    if COOKIES_FILE and os.path.isfile(COOKIES_FILE):
        return
    if COOKIES_FROM_BROWSER:
        return

    print()
    print("=" * 60)
    parts = []
    if has_ig:
        parts.append("Instagram")
    if has_x:
        parts.append("X (Twitter)")
    print(f"检测到 {' / '.join(parts)} 链接，需要登录后才能下载（X 建议登录以获取高清）。")
    print("=" * 60)
    print("即将打开登录页，请完成登录后回到本窗口按 回车 继续。")
    if has_ig:
        webbrowser.open("https://www.instagram.com")
    if has_x:
        webbrowser.open("https://x.com")
    input("登录完成后，请回到本窗口按 回车 继续... ")
    print()
    print("请选择您用来登录的浏览器（脚本将读取该浏览器的登录状态，仅读取、不保存密码）：")
    print("  1 = Chrome  （下载时需完全关闭浏览器）")
    print("  2 = Firefox （推荐：可保持打开）")
    print("  3 = Edge    （下载时需完全关闭浏览器）")
    print("  4 = 我已导出 cookies 文件（Netscape 格式），指定路径")
    print("  注意：Chrome/Edge 打开时会锁定 cookie，无法读取。请下载前完全关闭该浏览器，或选 Firefox。")
    if has_x:
        print("  X (Twitter)：导出 cookie 时请在 x.com 页面导出，或与 Instagram 合并到同一 cookies.txt。")
    choice = input("请输入 1/2/3/4 [默认 1]: ").strip().lower() or "1"

    if choice == "4":
        path = input("请输入 cookies 文件完整路径: ").strip().strip('"')
        if path and os.path.isfile(path):
            COOKIES_FILE = path
            _append_or_set_env("COOKIES_FILE", path)
            print("已保存到 .env，之后运行将自动使用该 cookies 文件。")
        else:
            print("文件不存在或路径无效，本次将不携带 cookies 下载（Instagram 可能仍会失败）。")
        return

    browser_map = {"1": "chrome", "2": "firefox", "3": "edge"}
    browser = browser_map.get(choice, "chrome")
    COOKIES_FROM_BROWSER = browser
    _append_or_set_env("COOKIES_FROM_BROWSER", browser)
    print(f"已保存到 .env（COOKIES_FROM_BROWSER={browser}），之后运行将自动使用该浏览器登录状态。")
    if browser in ("chrome", "edge"):
        print("重要：运行下载前请完全关闭该浏览器，否则会报「Could not copy Chrome cookie database」。")
    print("=" * 60)
    print()


def ensure_browser_cookies_ready() -> None:
    """
    若使用 Chrome/Edge 读 cookie，先检测能否读取；若不能则等待用户关闭浏览器后重试，
    避免整批 22 条都报同一错误「虚假运行」。用户可输入 q 跳过检测继续运行。
    """
    if not COOKIES_FROM_BROWSER or COOKIES_FROM_BROWSER not in ("chrome", "edge"):
        return
    browser_name = "Microsoft Edge" if COOKIES_FROM_BROWSER == "edge" else "Google Chrome"
    while True:
        if _can_read_browser_cookies(COOKIES_FROM_BROWSER):
            return
        print()
        print("无法读取浏览器 cookie（" + browser_name + " 可能仍在运行或未完全退出）。")
        print("请完全关闭所有窗口，并在「任务管理器」中结束所有「" + browser_name + "」相关进程后，按回车重试。")
        print("若已关闭仍报错，可改用 Firefox：.env 中设置 COOKIES_FROM_BROWSER=firefox。")
        print("输入 q 则跳过检测继续运行（下载 Instagram 等可能全部失败）。")
        r = input("请选择 [回车=重试, q=跳过]: ").strip().lower()
        if r == "q":
            return
        print("正在重试检测…")


def _column_letter_to_index(col: str) -> int:
    """A->0, B->1, ..., Z->25, AA->26"""
    i = 0
    for c in col:
        i = i * 26 + (ord(c) - ord("A") + 1)
    return i - 1


def _extract_key_from_url(url: str) -> str:
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    if m:
        return m.group(1)
    return ""


def get_drive_creds():
    """获取 Drive 上传用凭证：若有 client_secret 则用 OAuth（你的账号），否则用服务账号。"""
    if CLIENT_SECRET_PATH and os.path.isfile(CLIENT_SECRET_PATH):
        creds = None
        if TOKEN_PATH and os.path.isfile(TOKEN_PATH):
            creds = OAuth2Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_PATH, SCOPES)
                creds = flow.run_local_server(port=0)
            if TOKEN_PATH:
                with open(TOKEN_PATH, "w") as f:
                    f.write(creds.to_json())
        return creds
    return ServiceAccountCredentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)


def build_drive_service(creds):
    http = AuthorizedHttp(creds, http=httplib2.Http(timeout=DRIVE_HTTP_TIMEOUT))
    return build("drive", "v3", http=http, cache_discovery=False)


def get_sheet_data():
    """从 Google 表格读取 (url, name, 行号) 列表，并返回 sheet 供写回链接。"""
    key = SPREADSHEET_KEY or (_extract_key_from_url(SPREADSHEET_URL) if SPREADSHEET_URL else "")
    if not key:
        raise SystemExit("请设置 SPREADSHEET_URL 或 SPREADSHEET_KEY")

    creds = ServiceAccountCredentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    workbook = gc.open_by_key(key)
    sheet = workbook.worksheet(SHEET_NAME) if SHEET_NAME else workbook.sheet1

    url_col = _column_letter_to_index(URL_COLUMN)
    name_col = _column_letter_to_index(NAME_COLUMN)
    all_rows = sheet.get_all_values()

    data = []
    for idx, row in enumerate(all_rows[HEADER_ROWS:]):
        if len(row) <= max(url_col, name_col):
            continue
        url = (row[url_col] or "").strip()
        name = (row[name_col] or "").strip()
        if not url or not name:
            continue
        if not url.startswith("http"):
            continue
        safe_name = re.sub(r'[\r\n\t]', " ", name)
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", safe_name)
        safe_name = re.sub(r'\s+', " ", safe_name).strip()[:200]
        sheet_row_1based = HEADER_ROWS + idx + 1
        data.append((url, safe_name, sheet_row_1based))
    return data, sheet


def _extract_feishu_text_or_link(val) -> str:
    """从飞书字段值提取纯文本/链接（兼容字符串、超链接对象、列表格式）。"""
    if val is None:
        return ""
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, list) and val:
        item = val[0]
        if isinstance(item, dict):
            return (item.get("link") or item.get("text") or item.get("value") or "").strip()
        if isinstance(item, str):
            return item.strip()
    if isinstance(val, dict):
        return (val.get("link") or val.get("text") or "").strip()
    return ""


def get_feishu_data():
    """从飞书多维表格读取待处理记录，返回 (data, token, field_ids)。
    data 每项：(url, base_name, record_id, has_drive_link, has_cover)
    has_drive_link / has_cover 标记该记录在飞书中是否已有对应内容，均为 True 时自动跳过。
    最多返回 FEISHU_MAX_BATCH 条。
    """
    import feishu as _feishu

    if not FEISHU_URL_FIELD:
        raise SystemExit("请在 .env 中设置 FEISHU_URL_FIELD（飞书中存放视频链接的列名，如：发布链接）")
    if not _feishu.FEISHU_MATCH_FIELD:
        raise SystemExit("请在 .env 中设置 FEISHU_MATCH_FIELD（飞书中存放广告名的列名）")

    print("飞书：正在获取 token…")
    token = _feishu.feishu_tenant_token()
    if not token:
        raise SystemExit("飞书 token 获取失败，请检查 FEISHU_APP_ID / FEISHU_APP_SECRET")

    field_ids = _feishu.feishu_get_field_ids(token)
    if not field_ids:
        raise SystemExit("飞书字段列表获取失败，请检查 FEISHU_APP_TOKEN / FEISHU_TABLE_ID")

    required = [FEISHU_URL_FIELD, _feishu.FEISHU_MATCH_FIELD]
    missing = [f for f in required if f not in field_ids]
    if missing:
        raise SystemExit(
            f"飞书表中找不到以下列，请检查 .env 列名拼写：{missing}\n现有列（部分）：{list(field_ids.keys())[:20]}"
        )

    FEISHU_DATE_FIELD = "Upload Achieve Date(投放)"  # 按此列日期从新到旧排序

    print("飞书：正在拉取表格记录…")
    all_records = _feishu.feishu_list_records(token)
    print(f"飞书：共获取 {len(all_records)} 条记录，正在筛选…")

    _invalid_url_prefixes = (
        "https://www.tiktok.com/?",
        "https://tiktok.com/?",
        "https://www.instagram.com/?",
        "https://www.youtube.com/?",
    )

    candidates = []
    skipped_done = 0
    skipped_empty = 0

    for rec in all_records:
        fields = rec.get("fields") or {}
        record_id = rec.get("record_id", "")

        url = _extract_feishu_text_or_link(fields.get(FEISHU_URL_FIELD))
        if not url or not url.startswith("http") or any(url.startswith(p) for p in _invalid_url_prefixes):
            skipped_empty += 1
            continue

        name = _extract_feishu_text_or_link(fields.get(_feishu.FEISHU_MATCH_FIELD))
        if not name:
            skipped_empty += 1
            continue

        base_name = re.sub(r'[\r\n\t]', " ", name)
        base_name = re.sub(r'[<>:"/\\|?*]', "_", base_name)
        base_name = re.sub(r'\s+', " ", base_name).strip()[:200]

        drive_val = fields.get(_feishu.FEISHU_DRIVE_LINK_FIELD) if _feishu.FEISHU_DRIVE_LINK_FIELD else None
        has_drive_link = bool(drive_val and _extract_feishu_text_or_link(drive_val))

        cover_val = fields.get(_feishu.FEISHU_FILE_FIELD) if _feishu.FEISHU_FILE_FIELD else None
        has_cover = bool(cover_val and isinstance(cover_val, list) and len(cover_val) > 0)

        if has_drive_link and has_cover:
            skipped_done += 1
            continue

        # 读取日期字段（飞书日期列返回毫秒时间戳或字符串，统一转为可比较的数值）
        date_val = fields.get(FEISHU_DATE_FIELD)
        if isinstance(date_val, (int, float)):
            sort_key = date_val
        elif isinstance(date_val, str) and date_val.strip():
            try:
                sort_key = float(date_val.strip())
            except ValueError:
                sort_key = 0
        else:
            sort_key = 0

        candidates.append((sort_key, url, base_name, record_id, has_drive_link, has_cover))

    # 按日期从新到旧排序，只取最新一天的所有记录
    candidates.sort(key=lambda x: x[0], reverse=True)

    import datetime
    def _ts(ms):
        try:
            return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")
        except Exception:
            return "未知"

    # 找出最新日期，只取同一天的
    latest_date = _ts(candidates[0][0]) if candidates else None
    if latest_date and latest_date != "未知":
        candidates = [c for c in candidates if _ts(c[0]) == latest_date]
    else:
        # 没有日期信息时回退到最多 FEISHU_MAX_BATCH 条
        candidates = candidates[:FEISHU_MAX_BATCH]

    data = [(url, base_name, rid, hdl, hc) for _, url, base_name, rid, hdl, hc in candidates]

    skip_msg = []
    if skipped_done:
        skip_msg.append(f"{skipped_done} 条已完成跳过")
    if skipped_empty:
        skip_msg.append(f"{skipped_empty} 条无链接/名称跳过")
    if latest_date:
        skip_msg.append(f"仅处理最新日期 {latest_date}")
    print(f"飞书：{len(data)} 条需要处理。{'（' + '、'.join(skip_msg) + '）' if skip_msg else ''}")
    return data, token, field_ids


def _is_youtube_url(url: str) -> bool:
    """判断是否为 YouTube / YouTube Shorts 链接（用于回退策略）。"""
    return "youtube.com" in url or "youtu.be" in url


def _is_youtube_shorts_url(url: str) -> bool:
    """判断是否为 YouTube Shorts 链接。"""
    return "youtube.com/shorts/" in url


def download_video(
    url: str,
    output_dir: Path,
    base_name: str,
    cookies_file: Optional[str] = None,
    with_thumbnail: bool = False,
    thumb_base_name: Optional[str] = None,
) -> Tuple[Optional[Path], Optional[Path], Optional[str]]:
    """
    用 yt-dlp 下载视频到 output_dir，支持 Instagram / X (Twitter) / TikTok / YouTube / YouTube Shorts / 小红书 等；画质优先 bestvideo+bestaudio 高清。
    with_thumbnail=True 时同时下载封面图（与视频同目录，命名为左列文件名，不含 _cover）。
    画质：优先 bestvideo+bestaudio 合并，确保原画质或最高可用画质。
    YouTube：优先 android_vr（无需 GVS PO Token）；若格式不可用再回退 ios,mweb。
    返回 (视频路径, 封面路径或 None, 失败时的详细错误或 None)。
    """
    out_tpl = str(output_dir / f"{base_name}.%(ext)s")
    is_yt = _is_youtube_url(url)
    is_shorts = _is_youtube_shorts_url(url)
    # Shorts 优先用 web 客户端（较少触发限速且无需 PO Token）；
    # 普通 YouTube 先试 android_vr（无需 GVS PO Token），失败再试 ios,mweb；
    # 非 YouTube 只跑一轮；--extractor-args 仅作用于对应站点。
    extractor_args_list = (
        ["youtube:player_client=android_vr", "youtube:player_client=ios,mweb"]
        if is_yt  # Shorts 与普通 YouTube 同策略，android_vr 无需 JS 挑战
        else ["youtube:player_client=ios,mweb"]
    )
    ig_hint = _instagram_unsupported_url_hint(url)
    if ig_hint:
        print(f"  下载失败: {ig_hint}")
        return None, None, ig_hint

    last_err: Optional[str] = None
    for extractor_args in extractor_args_list:
        cmd = [
            "yt-dlp",
            "-f", "bestvideo+bestaudio/bestvideo/best",  # 优先画质；TikTok 等常无 bestvideo 时用 best，后续会拒绝 .m4a
            "--merge-output-format", "mp4",
            "-o", out_tpl,
            "--no-part",
            "-N", "4",                   # 4 个并发分片，对 DASH 流效果明显
            "--throttled-rate", "100K",  # YouTube 限速时自动重试其他格式
            "--socket-timeout", str(SOCKET_TIMEOUT),
            "--retries", str(DOWNLOAD_RETRIES),
            "--fragment-retries", str(DOWNLOAD_RETRIES),
            "--extractor-args", extractor_args,
            *_YT_JS_ARGS,               # Node.js + EJS 远程组件，解决 YouTube JS 挑战
            url,
        ]
        if with_thumbnail:
            thumb_name = thumb_base_name or base_name
            thumb_tpl = str(output_dir / f"{thumb_name}.%(ext)s")
            cmd.extend(["--write-thumbnail", "-o", f"thumbnail:{thumb_tpl}"])
        if cookies_file and os.path.isfile(cookies_file):
            cmd.extend(["--cookies", cookies_file])
        elif COOKIES_FROM_BROWSER:
            cmd.extend(["--cookies-from-browser", COOKIES_FROM_BROWSER])
        try:
            if is_yt:
                pc = extractor_args.split("=", 1)[-1] if "=" in extractor_args else extractor_args
                label = "Shorts" if is_shorts else "YouTube"
                print(f"  yt-dlp 下载中（{label} player_client={pc}），最长约 {DOWNLOAD_TIMEOUT}s，请稍候…")
            else:
                print(f"  yt-dlp 下载中，最长约 {DOWNLOAD_TIMEOUT}s，请稍候…")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT)
            if result.returncode == 0:
                last_err = None
                break
            raw = (result.stderr or result.stdout or ("exit " + str(result.returncode))).strip()
            err = _sanitize_ytdlp_stderr(raw) or raw
            last_err = err
            print(f"  下载失败: {err[:500]}" + ("…" if len(err) > 500 else ""))
            raw_l = raw.lower()
            if "marked as broken" in raw_l or "yt-dlp -u" in raw_l:
                print("  提示: 执行 python -m pip install -U yt-dlp 升级到最新版；Instagram 还需在 .env 中配置 COOKIES_FILE 或 COOKIES_FROM_BROWSER。")
            if _is_cookie_database_error(raw):
                print("  提示: 请完全关闭 Chrome/Edge，或在任务管理器中结束相关进程后重试；或改用 Firefox（.env 中 COOKIES_FROM_BROWSER=firefox）。")
            # YouTube：android_vr 失败且可能是格式/校验问题时，再试 ios,mweb
            if is_yt and extractor_args == "youtube:player_client=android_vr":
                if any(
                    x in raw
                    for x in (
                        "Requested format is not available",
                        "Only images are available",
                        "n challenge solving failed",
                    )
                ):
                    print("  正在换用 ios/mweb 客户端重试…")
                    continue
            return None, None, err
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            last_err = str(e)
            print(f"  下载失败: {e}")
            return None, None, last_err
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            print(f"  下载失败: {last_err}")
            return None, None, last_err
    if last_err:
        return None, None, last_err
    # 只认视频格式，拒绝 .m4a 等纯音频（Meta 等投放要求 MP4 视频）
    VIDEO_EXTENSIONS = (".mp4", ".mkv", ".webm", ".m4v", ".mov")
    video_path = None
    for f in output_dir.iterdir():
        if f.suffix.lower() in VIDEO_EXTENSIONS and f.stem == base_name:
            video_path = f
            break
    if not video_path:
        video_path = output_dir / f"{base_name}.mp4" if (output_dir / f"{base_name}.mp4").is_file() else None
    # 若只有 .m4a 等音频：不视为有效视频，报错便于投放场景排查
    if not video_path and (output_dir / f"{base_name}.m4a").is_file():
        return None, None, "仅获取到音频(m4a)，已跳过；需要视频格式(MP4)用于 Meta 等投放"
    thumb_name_for_find = thumb_base_name or base_name
    thumb_path = _find_thumbnail(output_dir, thumb_name_for_find) if with_thumbnail else None
    if with_thumbnail and not thumb_path and video_path:
        # 若平台未提供封面（少数情况），用 ffmpeg 从视频截取一帧作为封面
        thumb_path = _extract_frame_as_cover(video_path, output_dir, thumb_name_for_find)
        if thumb_path:
            print("  无平台封面，已从视频截取一帧作为封面")
    return video_path, thumb_path, None


def download_thumbnail_only(
    url: str, output_dir: Path, base_name: str, cookies_file: Optional[str] = None
) -> Tuple[Optional[Path], Optional[Path], Optional[str]]:
    """只下载封面图（不下载视频），返回 (None, 封面路径, 失败时的简短原因)。封面按左列文件名命名，不含 _cover。"""
    ig_hint = _instagram_unsupported_url_hint(url)
    if ig_hint:
        print(f"  下载封面失败: {ig_hint}")
        return None, None, ig_hint

    thumb_tpl = str(output_dir / f"{base_name}.%(ext)s")
    # 先试仅要封面、不指定 format；若报 Requested format / Only images 再用 bestimage 重试
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-thumbnail",
        "-o", thumb_tpl,
        "--socket-timeout", str(SOCKET_TIMEOUT),
        "--retries", str(DOWNLOAD_RETRIES),
        *_YT_JS_ARGS,
        url,
    ]
    if cookies_file and os.path.isfile(cookies_file):
        cmd.extend(["--cookies", cookies_file])
    elif COOKIES_FROM_BROWSER:
        cmd.extend(["--cookies-from-browser", COOKIES_FROM_BROWSER])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=max(120, SOCKET_TIMEOUT + 60))
        raw = (result.stderr or result.stdout or "").strip()
        err = raw
        if result.returncode != 0 and ("Requested format" in raw or "Only images" in raw):
            # YouTube 等仅提供图片时：用 bestimage 再试一次，且不用 android 客户端
            cmd_retry = [
                "yt-dlp", "--skip-download", "--write-thumbnail", "-o", thumb_tpl,
                "--format", "bestimage",
                "--socket-timeout", str(SOCKET_TIMEOUT),
                "--retries", str(DOWNLOAD_RETRIES),
                *_YT_JS_ARGS,
                url,
            ]
            if cookies_file and os.path.isfile(cookies_file):
                cmd_retry.extend(["--cookies", cookies_file])
            elif COOKIES_FROM_BROWSER:
                cmd_retry.extend(["--cookies-from-browser", COOKIES_FROM_BROWSER])
            result = subprocess.run(cmd_retry, capture_output=True, text=True, timeout=max(120, SOCKET_TIMEOUT + 60))
            raw = (result.stderr or result.stdout or "").strip()
            err = raw
        if result.returncode != 0:
            # 最后兜底：先完整下载视频+封面，保留封面后删掉视频（部分平台必须下视频才有封面）
            print(f"  仅拉封面失败，改为先下载视频再取封面并删除视频…")
            video_path, thumb_path, download_err = download_video(
                url, output_dir, base_name, cookies_file, with_thumbnail=True
            )
            if video_path and video_path.is_file():
                try:
                    video_path.unlink()
                except OSError:
                    pass
            if thumb_path:
                return None, thumb_path, None
            # 返回完整错误信息，便于结尾汇总复制
            combined = (download_err or err or ("exit " + str(result.returncode))).strip()
            detail = _sanitize_ytdlp_stderr(combined) or combined
            print(f"  下载封面失败: {detail[:200]}" + ("…" if len(detail) > 200 else ""))
            if _is_cookie_database_error(detail):
                print("  提示: 请完全关闭 Chrome/Edge 或在任务管理器中结束相关进程后重试；或改用 Firefox。")
            return None, None, detail
        thumb_path = _find_thumbnail(output_dir, base_name)
        if thumb_path is None:
            # yt-dlp 返回成功但未找到预期扩展名的封面文件，带出 stderr 便于排查
            no_file_msg = (_sanitize_ytdlp_stderr(err) or err or "yt-dlp 返回成功但未找到封面文件（.jpg/.jpeg/.webp/.png/.image）").strip()
            return None, None, no_file_msg
        return None, thumb_path, None
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"  下载封面失败: {e}")
        if _is_cookie_database_error(str(e)):
            print("  提示: 请完全关闭 Chrome/Edge 或在任务管理器中结束相关进程后重试；或改用 Firefox。")
        return None, None, str(e).strip()
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        print(f"  下载封面失败: {msg}")
        return None, None, msg


def _find_thumbnail(output_dir: Path, base_name: str) -> Optional[Path]:
    """在 output_dir 下按左列文件名查找封面（含 .jpg/.jpeg/.webp/.png/.image，TikTok 等可能用 .image）。"""
    for ext in (".jpg", ".jpeg", ".webp", ".png", ".image"):
        p = output_dir / f"{base_name}{ext}"
        if p.is_file():
            return p
    return None


def _extract_frame_as_cover(video_path: Path, output_dir: Path, base_name: str) -> Optional[Path]:
    """用 ffmpeg 从视频中截取一帧（约第 1 秒）保存为 base_name.jpg，无 ffmpeg 则返回 None。"""
    out_path = output_dir / f"{base_name}.jpg"
    try:
        # -ss 1 取第 1 秒处，避免开头黑屏；-vframes 1 只取一帧
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path), "-ss", "1", "-vframes", "1", str(out_path)],
            capture_output=True,
            timeout=30,
        )
        return out_path if out_path.is_file() else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _set_drive_file_anyone_can_view(service, file_id: str) -> None:
    """将 Drive 文件设为「知道链接的任何人可查看」，便于表格/飞书内显示图片。"""
    try:
        service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
        ).execute()
    except Exception:
        pass  # 共享盘等可能失败，忽略；用户可手动改共享设置


def upload_to_drive(
    service, file_path: Path, name: str, folder_id: Optional[str], allow_public_view: bool = False,
    creds=None,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """上传文件到 Google Drive，返回 (是否成功, 查看链接, file_id)。
    优先用 requests（AuthorizedSession）发起分块上传，绕过 httplib2 在某些网络环境下
    丢失 Location header 的问题；creds 为 None 时回退到原 service 方式。
    """
    if creds is not None:
        return _upload_to_drive_requests(creds, file_path, name, folder_id, allow_public_view, service)
    # 回退：原 httplib2 路径
    body = {"name": name}
    if folder_id:
        body["parents"] = [folder_id]
    media = MediaFileUpload(str(file_path), resumable=True, chunksize=4 * 1024 * 1024)
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        try:
            result = (
                service.files()
                .create(body=body, media_body=media, fields="id")
                .execute(num_retries=8)
            )
            file_id = result.get("id")
            if file_id and allow_public_view:
                _set_drive_file_anyone_can_view(service, file_id)
            link = f"https://drive.google.com/file/d/{file_id}/view" if file_id else None
            return True, link, file_id
        except Exception as e:
            err_msg = str(e)
            print(f"  上传失败(第{attempt}次): {err_msg[:200]}")
            if attempt < max_attempts:
                wait = 2 ** attempt
                print(f"  等待 {wait}s 后重试…")
                time.sleep(wait)
                media = MediaFileUpload(str(file_path), resumable=True, chunksize=4 * 1024 * 1024)
    return False, None, None


def _upload_to_drive_requests(
    creds, file_path: Path, name: str, folder_id: Optional[str], allow_public_view: bool, service
) -> Tuple[bool, Optional[str], Optional[str]]:
    """用 requests（AuthorizedSession）做分块上传，避免 httplib2 redirect 问题。"""
    from google.auth.transport.requests import AuthorizedSession
    import json as _json

    CHUNK = 8 * 1024 * 1024  # 8 MB
    file_size = file_path.stat().st_size
    metadata = {"name": name}
    if folder_id:
        metadata["parents"] = [folder_id]

    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        try:
            session = AuthorizedSession(creds)
            # 1. 发起 resumable upload，获取上传 URL
            init_resp = session.post(
                "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
                headers={"Content-Type": "application/json; charset=UTF-8",
                         "X-Upload-Content-Length": str(file_size)},
                data=_json.dumps(metadata).encode(),
                timeout=60,
            )
            if init_resp.status_code not in (200, 201):
                raise Exception(f"初始化上传失败 HTTP {init_resp.status_code}: {init_resp.text[:200]}")
            upload_url = init_resp.headers.get("Location")
            if not upload_url:
                raise Exception("初始化响应缺少 Location header")

            # 2. 分块 PUT
            file_id = None
            with open(file_path, "rb") as f:
                offset = 0
                while offset < file_size:
                    chunk = f.read(CHUNK)
                    end = offset + len(chunk) - 1
                    put_resp = session.put(
                        upload_url,
                        headers={
                            "Content-Range": f"bytes {offset}-{end}/{file_size}",
                            "Content-Length": str(len(chunk)),
                        },
                        data=chunk,
                        timeout=DRIVE_HTTP_TIMEOUT,
                    )
                    if put_resp.status_code in (200, 201):
                        file_id = put_resp.json().get("id")
                        break
                    if put_resp.status_code == 308:  # Resume Incomplete，继续下一块
                        offset += len(chunk)
                        continue
                    raise Exception(f"上传块失败 HTTP {put_resp.status_code}: {put_resp.text[:200]}")

            if not file_id:
                raise Exception("上传完成但未获取到 file_id")
            if allow_public_view:
                _set_drive_file_anyone_can_view(service, file_id)
            link = f"https://drive.google.com/file/d/{file_id}/view"
            return True, link, file_id

        except Exception as e:
            print(f"  上传失败(第{attempt}次): {str(e)[:200]}")
            if attempt < max_attempts:
                wait = 2 ** attempt
                print(f"  等待 {wait}s 后重试…")
                time.sleep(wait)
    return False, None, None


def main():
    # 命令行覆盖：python main.py video | cover | both，不传则用 .env（影响 need_video/need_cover 逻辑）
    force_video, force_cover = None, None
    if len(sys.argv) > 1:
        mode = sys.argv[1].strip().lower()
        if mode == "video":
            force_video, force_cover = True, False
        elif mode == "cover":
            force_video, force_cover = False, True
        elif mode == "both":
            force_video, force_cover = True, True

    # 从飞书读取待处理记录
    data, feishu_token, feishu_field_ids = get_feishu_data()
    if not data:
        print("没有待处理的记录（所有记录已完成，或飞书表中无有效链接/名称）。")
        return

    import feishu as _feishu
    ensure_login_if_needed([(url, name, 0) for url, name, *_ in data])
    ensure_browser_cookies_ready()

    net_msg = ""
    if SLOW_NETWORK or SOCKET_TIMEOUT > 30 or DOWNLOAD_DELAY_SECONDS > 0:
        slow_note = "慢速网络模式 " if SLOW_NETWORK else ""
        net_msg = f" [{slow_note}超时={SOCKET_TIMEOUT}s, 重试={DOWNLOAD_RETRIES}, 间隔={DOWNLOAD_DELAY_SECONDS}s, 单条最长={DOWNLOAD_TIMEOUT}s]"
    print(f"开始处理 {len(data)} 条（每次上限 {FEISHU_MAX_BATCH} 条）{net_msg}")

    cookies = COOKIES_FILE or None
    folder_id = DRIVE_FOLDER_ID or None
    drive_creds = get_drive_creds()
    drive_service = build_drive_service(drive_creds)

    failures = []  # (base_name, record_id, 原因, 详细错误)
    success_count = 0

    for i, (url, base_name, record_id, has_drive_link, has_cover) in enumerate(data, 1):
        # 命令行模式覆盖按需逻辑
        if force_video is not None:
            need_video = force_video
            need_cover = force_cover
        else:
            need_video = not has_drive_link
            need_cover = not has_cover

        status_parts = []
        if not need_video and has_drive_link:
            status_parts.append("Drive链接已有")
        if not need_cover and has_cover:
            status_parts.append("封面已有")
        status_hint = f"（{', '.join(status_parts)}）" if status_parts else ""
        print(f"[{i}/{len(data)}] {base_name}{status_hint}")

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path, thumb_path = None, None
            drive_link = ""
            item_failed = False

            if need_video:
                video_path, thumb_path, download_err = download_video(
                    url, Path(tmpdir), "video", cookies,
                    with_thumbnail=need_cover, thumb_base_name=base_name,
                )
                if not video_path:
                    if _is_cookie_database_error(download_err):
                        print("  请完全关闭 Chrome/Edge 后按回车重试，或输入 s 跳过。")
                        r = input("  [回车=重试, s=跳过]: ").strip().lower()
                        if r != "s":
                            video_path, thumb_path, download_err = download_video(
                                url, Path(tmpdir), "video", cookies,
                                with_thumbnail=need_cover, thumb_base_name=base_name,
                            )
                    if not video_path:
                        failures.append((base_name, record_id, "下载视频失败", download_err or "未知错误"))
                        continue
                final_name = base_name if base_name.endswith(video_path.suffix) else base_name + video_path.suffix
                ok, drive_link, _ = upload_to_drive(
                    drive_service, video_path, final_name, folder_id,
                    allow_public_view=False, creds=drive_creds,
                )
                if ok:
                    print(f"  已上传视频到 Drive: {final_name}")
                else:
                    print(f"  Drive 上传失败，跳过: {final_name}")
                    failures.append((base_name, record_id, "Drive 上传失败", "详见上方输出"))
                    item_failed = True

            elif need_cover:
                # 只需封面，不下载视频
                _, thumb_path, thumb_err = download_thumbnail_only(url, Path(tmpdir), base_name, cookies)
                if not thumb_path:
                    failures.append((base_name, record_id, "下载封面失败", thumb_err or "未知错误"))
                    continue
                print(f"  已下载封面")

            # 统一把 .image 后缀改为 .jpg
            if thumb_path:
                ext = ".jpg" if thumb_path.suffix.lower() == ".image" else thumb_path.suffix
                thumb_name = base_name + ext
            else:
                thumb_name = None

            # 写入飞书
            ftok = None
            if need_cover and thumb_path and thumb_name:
                ftok = _feishu.feishu_upload_media(thumb_path, thumb_name, feishu_token)
                if not ftok:
                    print(f"  飞书封面上传失败，仅写链接列")

            if (ftok or (need_video and drive_link)) and not item_failed:
                _feishu.feishu_update_record(
                    feishu_token, record_id, ftok, feishu_field_ids,
                    drive_link=drive_link or None,
                )

            # 本地导出（可选）
            if thumb_path and thumb_name and FEISHU_EXPORT_DIR:
                export_root = Path(FEISHU_EXPORT_DIR).expanduser().resolve()
                export_root.mkdir(parents=True, exist_ok=True)
                covers_dir = export_root / "covers"
                covers_dir.mkdir(exist_ok=True)
                try:
                    import shutil
                    shutil.copy2(thumb_path, covers_dir / thumb_name)
                    csv_path = export_root / "links.csv"
                    write_header = not csv_path.is_file()
                    with open(csv_path, "a", newline="", encoding="utf-8") as f:
                        w = csv.writer(f)
                        if write_header:
                            w.writerow([FEISHU_MATCH_FIELD or "命名", FEISHU_DRIVE_LINK_FIELD or "视频Drive链接", "封面文件名"])
                        w.writerow([base_name, drive_link, thumb_name])
                except Exception as e:
                    print(f"  本地导出失败: {e}")

            if not item_failed:
                success_count += 1

        if i < len(data) and DOWNLOAD_DELAY_SECONDS > 0:
            time.sleep(DOWNLOAD_DELAY_SECONDS)

    # 汇总
    print(f"\n{'=' * 60}")
    print(f"完成：共 {len(data)} 条，成功 {success_count} 条，失败 {len(failures)} 条。")
    if failures:
        print(f"\n失败明细：")
        for name, record_id, reason, detail in failures:
            short_detail = (detail or "").splitlines()[0][:120] if detail else ""
            print(f"  - {name}  [record_id: {record_id}]")
            print(f"    原因: {reason}  |  {short_detail}")
        print(f"\n{'=' * 60}")
        print("失败详情（完整）")
        print("=" * 60)
        for idx, (name, record_id, reason, detail) in enumerate(failures, 1):
            print(f"\n【{idx}】{name}  (record_id: {record_id})")
            print(f"  原因: {reason}")
            for line in (detail or "").splitlines():
                print(f"    {line}")
        print("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].strip().lower() in ("-h", "--help"):
        print("用法: python main.py [video|cover|both]")
        print("  video  只下载并上传视频到 Drive，写回链接")
        print("  cover  只下载封面并导出到 FEISHU_EXPORT_DIR（不下载视频）")
        print("  both   视频+封面都做（默认）")
        sys.exit(0)
    main()
