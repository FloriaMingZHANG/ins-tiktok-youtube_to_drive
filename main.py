#!/usr/bin/env python3
"""
从 Google 表格读取一列视频链接、一列命名，
依次下载（支持 Instagram / TikTok / YouTube / YouTube Shorts 等）并按命名上传到 Google Drive。
"""

import csv
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple

import gspread
from dotenv import load_dotenv
from gspread_formatting import cellFormat, color, format_cell_range
from google.oauth2.credentials import Credentials as OAuth2Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
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


def download_video(
    url: str, output_dir: Path, base_name: str, cookies_file: Optional[str] = None, with_thumbnail: bool = False
) -> Tuple[Optional[Path], Optional[Path], Optional[str]]:
    """
    用 yt-dlp 下载视频到 output_dir，支持 Instagram / TikTok / YouTube / YouTube Shorts 等。
    with_thumbnail=True 时同时下载封面图（与视频同目录，命名为 base_name_cover）。
    返回 (视频路径, 封面路径或 None, 失败时的详细错误或 None)。
    """
    out_tpl = str(output_dir / f"{base_name}.%(ext)s")
    cmd = [
        "yt-dlp",
        "--merge-output-format", "mp4",
        "-o", out_tpl,
        "--no-part",
        "--extractor-args", "youtube:player_client=android",
        url,
    ]
    if with_thumbnail:
        thumb_tpl = str(output_dir / f"{base_name}_cover.%(ext)s")
        cmd.extend(["--write-thumbnail", "-o", f"thumbnail:{thumb_tpl}"])
    if cookies_file and os.path.isfile(cookies_file):
        cmd.extend(["--cookies", cookies_file])
    elif COOKIES_FROM_BROWSER:
        cmd.extend(["--cookies-from-browser", COOKIES_FROM_BROWSER])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            err = (result.stderr or result.stdout or ("exit " + str(result.returncode))).strip()
            print(f"  下载失败: {err[:500]}" + ("…" if len(err) > 500 else ""))
            return None, None, err
        video_path = None
        for f in output_dir.iterdir():
            if f.suffix.lower() in (".mp4", ".mkv", ".webm", ".m4a") and f.stem.startswith(base_name) and "_cover" not in f.stem:
                video_path = f
                break
        if not video_path:
            video_path = output_dir / f"{base_name}.mp4" if (output_dir / f"{base_name}.mp4").is_file() else None
        thumb_path = _find_thumbnail(output_dir, base_name) if with_thumbnail else None
        if with_thumbnail and not thumb_path and video_path:
            # 若平台未提供封面（少数情况），用 ffmpeg 从视频截取一帧作为封面
            thumb_path = _extract_frame_as_cover(video_path, output_dir, base_name)
            if thumb_path:
                print("  无平台封面，已从视频截取一帧作为封面")
        return video_path, thumb_path, None
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"  下载失败: {e}")
        return None, None, str(e)


def download_thumbnail_only(
    url: str, output_dir: Path, base_name: str, cookies_file: Optional[str] = None
) -> Tuple[Optional[Path], Optional[Path], Optional[str]]:
    """只下载封面图（不下载视频），返回 (None, 封面路径, 失败时的简短原因)。"""
    thumb_tpl = str(output_dir / f"{base_name}_cover.%(ext)s")
    # 先试仅要封面、不指定 format；若报 Requested format / Only images 再用 bestimage 重试
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-thumbnail",
        "-o", thumb_tpl,
        url,
    ]
    if cookies_file and os.path.isfile(cookies_file):
        cmd.extend(["--cookies", cookies_file])
    elif COOKIES_FROM_BROWSER:
        cmd.extend(["--cookies-from-browser", COOKIES_FROM_BROWSER])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        err = (result.stderr or result.stdout or "").strip()
        if result.returncode != 0 and ("Requested format" in err or "Only images" in err):
            # YouTube 等仅提供图片时：用 bestimage 再试一次，且不用 android 客户端
            cmd_retry = [
                "yt-dlp", "--skip-download", "--write-thumbnail", "-o", thumb_tpl,
                "--format", "bestimage",
                url,
            ]
            if cookies_file and os.path.isfile(cookies_file):
                cmd_retry.extend(["--cookies", cookies_file])
            elif COOKIES_FROM_BROWSER:
                cmd_retry.extend(["--cookies-from-browser", COOKIES_FROM_BROWSER])
            result = subprocess.run(cmd_retry, capture_output=True, text=True, timeout=120)
            err = (result.stderr or result.stdout or "").strip()
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
            detail = (download_err or err or ("exit " + str(result.returncode))).strip()
            print(f"  下载封面失败: {detail[:200]}" + ("…" if len(detail) > 200 else ""))
            return None, None, detail
        thumb_path = _find_thumbnail(output_dir, base_name)
        return None, thumb_path, None
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"  下载封面失败: {e}")
        return None, None, str(e).strip()


def _find_thumbnail(output_dir: Path, base_name: str) -> Optional[Path]:
    """在 output_dir 下查找 base_name_cover 的封面文件（.jpg/.jpeg/.webp/.png），找到则返回路径。"""
    for ext in (".jpg", ".jpeg", ".webp", ".png"):
        p = output_dir / f"{base_name}_cover{ext}"
        if p.is_file():
            return p
    return None


def _extract_frame_as_cover(video_path: Path, output_dir: Path, base_name: str) -> Optional[Path]:
    """用 ffmpeg 从视频中截取一帧（约第 1 秒）保存为 base_name_cover.jpg，无 ffmpeg 则返回 None。"""
    out_path = output_dir / f"{base_name}_cover.jpg"
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
    print(msg)
    cookies = COOKIES_FILE or None
    folder_id = DRIVE_FOLDER_ID or None
    drive_service = None
    if DO_VIDEO or thumb_col:
        creds = get_drive_creds()
        drive_service = build("drive", "v3", credentials=creds)
    failures = []  # (base_name, 原因, 详细错误信息, 表格行号)
    for i, (url, base_name, sheet_row) in enumerate(data, 1):
        print(f"[{i}/{len(data)}] {base_name}")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            video_path, thumb_path = None, None
            drive_link = ""
            if DO_VIDEO:
                video_path, thumb_path, download_err = download_video(
                    url, Path(tmpdir), "video", cookies, with_thumbnail=DO_COVER
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
                # 仅封面
                _, thumb_path, thumb_err = download_thumbnail_only(url, Path(tmpdir), "video", cookies)
                if not thumb_path:
                    failures.append((base_name, "下载封面失败", thumb_err or "未知错误", sheet_row))
                    continue
                print(f"  已下载封面")
            thumb_name = (base_name + "_cover" + thumb_path.suffix) if thumb_path else None
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
