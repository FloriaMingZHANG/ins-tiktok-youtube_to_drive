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
# Drive 上传（httplib2）单次连接超时，大文件或慢网可加大；默认慢网 20 分钟
DRIVE_HTTP_TIMEOUT = int(os.getenv("DRIVE_HTTP_TIMEOUT", "1200" if SLOW_NETWORK else "600").strip())

# yt-dlp 子进程 stderr 常混入本机 Python 的 FutureWarning/urllib3 等，干扰判断真实失败原因
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
    """Drive API 客户端；拉长 httplib2 超时，减少大文件上传时出现 timed out。"""
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
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", name)[:200]
        sheet_row_1based = HEADER_ROWS + idx + 1
        data.append((url, safe_name, sheet_row_1based))
    return data, sheet


def _is_youtube_url(url: str) -> bool:
    """判断是否为 YouTube / YouTube Shorts 链接（用于回退策略）。"""
    return "youtube.com" in url or "youtu.be" in url


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
    YouTube 若因 GVS PO Token/格式不可用失败，会自动用不需要 PO Token 的客户端（android_vr）重试。
    返回 (视频路径, 封面路径或 None, 失败时的详细错误或 None)。
    """
    out_tpl = str(output_dir / f"{base_name}.%(ext)s")
    # 可选：youtube 客户端。首次用 ios,mweb；失败且为 YouTube 时用 android_vr（无需 PO Token）
    extractor_args_list = [
        "youtube:player_client=ios,mweb",   # 绕过 web 的 n challenge
        "youtube:player_client=android_vr", # 回退：不需要 GVS PO Token，见 https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide
    ]
    last_err: Optional[str] = None
    for extractor_args in extractor_args_list:
        cmd = [
            "yt-dlp",
            "-f", "bestvideo+bestaudio/bestvideo/best",  # 优先画质；TikTok 等常无 bestvideo 时用 best，后续会拒绝 .m4a
            "--merge-output-format", "mp4",
            "-o", out_tpl,
            "--no-part",
            "--socket-timeout", str(SOCKET_TIMEOUT),
            "--retries", str(DOWNLOAD_RETRIES),
            "--extractor-args", extractor_args,
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
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT)
            if result.returncode == 0:
                last_err = None
                break
            raw = (result.stderr or result.stdout or ("exit " + str(result.returncode))).strip()
            err = _sanitize_ytdlp_stderr(raw) or raw
            last_err = err
            print(f"  下载失败: {err[:500]}" + ("…" if len(err) > 500 else ""))
            if _is_cookie_database_error(raw):
                print("  提示: 请完全关闭 Chrome/Edge，或在任务管理器中结束相关进程后重试；或改用 Firefox（.env 中 COOKIES_FROM_BROWSER=firefox）。")
            # 仅对 YouTube 且因格式/PO Token 导致不可用时，尝试下一客户端
            if extractor_args == "youtube:player_client=ios,mweb" and _is_youtube_url(url):
                if "Requested format is not available" in raw or "Only images are available" in raw or "GVS PO Token" in raw or "n challenge solving failed" in raw:
                    print("  正在用备用 YouTube 客户端重试（无需 PO Token）…")
                    continue
            return None, None, err
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            last_err = str(e)
            print(f"  下载失败: {e}")
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
    thumb_tpl = str(output_dir / f"{base_name}.%(ext)s")
    # 先试仅要封面、不指定 format；若报 Requested format / Only images 再用 bestimage 重试
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-thumbnail",
        "-o", thumb_tpl,
        "--socket-timeout", str(SOCKET_TIMEOUT),
        "--retries", str(DOWNLOAD_RETRIES),
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
    service, file_path: Path, name: str, folder_id: Optional[str], allow_public_view: bool = False
) -> Tuple[bool, Optional[str], Optional[str]]:
    """上传文件到 Google Drive，返回 (是否成功, 查看链接, file_id)。service 由调用方 build 一次传入，避免批量时重复建连。"""
    body = {"name": name}
    if folder_id:
        body["parents"] = [folder_id]
    media = MediaFileUpload(str(file_path), resumable=True)
    try:
        result = service.files().create(body=body, media_body=media, fields="id").execute()
        file_id = result.get("id")
        if file_id and allow_public_view:
            _set_drive_file_anyone_can_view(service, file_id)
        link = f"https://drive.google.com/file/d/{file_id}/view" if file_id else None
        return True, link, file_id
    except Exception as e:
        print(f"  上传失败: {e}")
        return False, None, None


def main():
    global DO_VIDEO, DO_COVER
    # 命令行覆盖：python main.py video | cover | both，不传则用 .env
    if len(sys.argv) > 1:
        mode = sys.argv[1].strip().lower()
        if mode == "video":
            DO_VIDEO, DO_COVER = True, False
        elif mode == "cover":
            DO_VIDEO, DO_COVER = False, True
        elif mode == "both":
            DO_VIDEO, DO_COVER = True, True
    data, sheet = get_sheet_data()
    if not data:
        print("没有可处理的链接/命名数据，请检查表格和 URL_COLUMN、NAME_COLUMN、HEADER_ROWS。")
        return
    if not DO_VIDEO and not DO_COVER:
        print("DO_VIDEO 与 DO_COVER 至少开启一个。用法: python main.py [video|cover|both]")
        return
    # 若有 Instagram 链接且未配置登录，弹出一劳永逸的登录引导并写入 .env
    ensure_login_if_needed(data)
    # 使用 Chrome/Edge 时先检测能否读 cookie，避免整批都报同一错误
    ensure_browser_cookies_ready()
    result_col = _column_letter_to_index(RESULT_COLUMN) + 1 if (RESULT_COLUMN and DO_VIDEO) else None
    if DO_VIDEO and not RESULT_COLUMN:
        print("提示: 未设置 RESULT_COLUMN，视频 Drive 链接将不会写回表格。请在 .env 中设置 RESULT_COLUMN（如 C）。")
    thumb_col = _column_letter_to_index(THUMBNAIL_COLUMN) + 1 if (THUMBNAIL_COLUMN and not SKIP_DRIVE_COVER and DO_COVER) else None
    with_thumb = DO_COVER and (bool(THUMBNAIL_COLUMN and not SKIP_DRIVE_COVER) or bool(FEISHU_EXPORT_DIR))
    msg = f"共 {len(data)} 条待处理。本次："
    msg += "视频" if DO_VIDEO else ""
    msg += "+封面" if DO_VIDEO and DO_COVER else ("封面" if DO_COVER else "")
    msg += "。"
    if result_col:
        msg += f" 视频链接写回第 {RESULT_COLUMN} 列。"
    if thumb_col:
        msg += f" 封面链接写回第 {THUMBNAIL_COLUMN} 列。"
    if DO_COVER and FEISHU_EXPORT_DIR and not thumb_col:
        msg += f" 封面原图导出到 {FEISHU_EXPORT_DIR}。"
    if SLOW_NETWORK or SOCKET_TIMEOUT > 30 or DOWNLOAD_DELAY_SECONDS > 0:
        slow_note = "慢速网络模式 " if SLOW_NETWORK else ""
        msg += f" [{slow_note}超时={SOCKET_TIMEOUT}s, 重试={DOWNLOAD_RETRIES}, 每条间隔={DOWNLOAD_DELAY_SECONDS}s, 单条最长={DOWNLOAD_TIMEOUT}s]"
    print(msg)
    cookies = COOKIES_FILE or None
    folder_id = DRIVE_FOLDER_ID or None
    drive_service = None
    if DO_VIDEO or thumb_col:
        creds = get_drive_creds()
        drive_service = build_drive_service(creds)
    failures = []  # (base_name, 原因, 详细错误信息, 表格行号)
    for i, (url, base_name, sheet_row) in enumerate(data, 1):
        print(f"[{i}/{len(data)}] {base_name}")
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path, thumb_path = None, None
            drive_link = ""
            if DO_VIDEO:
                video_path, thumb_path, download_err = download_video(
                    url, Path(tmpdir), "video", cookies, with_thumbnail=DO_COVER, thumb_base_name=base_name
                )
                if not video_path:
                    if _is_cookie_database_error(download_err):
                        print("  请完全关闭 Chrome/Edge（或任务管理器中结束进程）后按回车重试本条，或输入 s 跳过。")
                        r = input("  [回车=重试, s=跳过]: ").strip().lower()
                        if r != "s":
                            video_path, thumb_path, download_err = download_video(
                                url, Path(tmpdir), "video", cookies, with_thumbnail=DO_COVER, thumb_base_name=base_name
                            )
                    if not video_path:
                        failures.append((base_name, "下载视频失败", download_err or "未知错误", sheet_row))
                        continue
                final_name = base_name if base_name.endswith(video_path.suffix) else base_name + video_path.suffix
                ok, drive_link, _ = upload_to_drive(drive_service, video_path, final_name, folder_id, allow_public_view=False)
                if not ok:
                    ok, drive_link, _ = upload_to_drive(drive_service, video_path, final_name, folder_id, allow_public_view=False)  # 重试一次
                if ok:
                    print(f"  已上传视频: {final_name}")
                    if result_col and drive_link:
                        try:
                            sheet.update_cell(sheet_row, result_col, drive_link)
                            print(f"  已写回第 {RESULT_COLUMN} 列")
                        except Exception as e:
                            print(f"  写回第 {RESULT_COLUMN} 列失败: {e}")
                else:
                    print(f"  跳过上传视频: {final_name}")
            else:
                # 仅封面（按左列文件名命名，不含 _cover）
                _, thumb_path, thumb_err = download_thumbnail_only(url, Path(tmpdir), base_name, cookies)
                if not thumb_path:
                    failures.append((base_name, "下载封面失败", thumb_err or "未知错误", sheet_row))
                    continue
                print(f"  已下载封面")
            # 导出/上传时统一把 .image 改为 .jpg，避免系统无法识别
            if thumb_path:
                ext = ".jpg" if thumb_path.suffix.lower() == ".image" else thumb_path.suffix
                thumb_name = base_name + ext
            else:
                thumb_name = None
            if thumb_path and thumb_col:
                ok_thumb, _, thumb_file_id = upload_to_drive(
                    drive_service, thumb_path, thumb_name, folder_id, allow_public_view=True
                )
                if ok_thumb and thumb_file_id:
                    direct_url = f"https://drive.google.com/uc?export=view&id={thumb_file_id}"
                    sheet.update_cell(sheet_row, thumb_col, f'=IMAGE("{direct_url}")')
                    print(f"  已上传封面并在第 {THUMBNAIL_COLUMN} 列显示图片")
            if thumb_path and thumb_name and DO_COVER and FEISHU_EXPORT_DIR:
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
                    print(f"  已导出到 {export_root}（封面原图在 covers/，可复制到飞书）")
                except Exception as e:
                    print(f"  导出到本地失败: {e}")
        # 慢速网络：每条任务之间间隔，避免连接被限速或超时
        if i < len(data) and DOWNLOAD_DELAY_SECONDS > 0:
            time.sleep(DOWNLOAD_DELAY_SECONDS)
    # 汇总
    ok_count = len(data) - len(failures)
    print(f"\n共 {len(data)} 条：成功 {ok_count} 条。")
    if failures:
        print(f"失败 {len(failures)} 条：")
        for name, reason, _, _ in failures:
            print(f"  - {name}: {reason}")
        # 详细失败原因，便于复制
        print("\n" + "=" * 60)
        print("失败详情（可复制）")
        print("=" * 60)
        for idx, (name, reason, detail, _) in enumerate(failures, 1):
            print(f"\n【{idx}】{name}")
            print(f"  类型: {reason}")
            print(f"  详细:")
            for line in (detail or "").splitlines():
                print(f"    {line}")
            print()
        print("=" * 60)
        # 在表格中高亮失败行（整行浅红底）
        failed_rows = [row for (_, _, _, row) in failures]
        if failed_rows:
            try:
                fmt = cellFormat(backgroundColor=color(1.0, 0.85, 0.85))  # 浅红
                for row in failed_rows:
                    format_cell_range(sheet, f"{row}:{row}", fmt)
                print(f"已在表格中高亮 {len(failed_rows)} 行（失败行）。")
            except Exception as e:
                print(f"高亮失败行时出错（不影响结果）: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].strip().lower() in ("-h", "--help"):
        print("用法: python main.py [video|cover|both]")
        print("  video  只下载并上传视频到 Drive，写回链接")
        print("  cover  只下载封面并导出到 FEISHU_EXPORT_DIR（不下载视频）")
        print("  both   视频+封面都做（默认）")
        sys.exit(0)
    main()
