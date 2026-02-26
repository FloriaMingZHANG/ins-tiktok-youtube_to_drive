#!/usr/bin/env python3
"""
从 Google 表格读取一列视频链接、一列命名，
依次下载（支持 Instagram / TikTok / YouTube / YouTube Shorts 等）并按命名上传到 Google Drive。
"""

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

import gspread
from dotenv import load_dotenv
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

# Drive
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "").strip()

# 可选：cookies 文件（部分平台如 Ins/TikTok 需登录时使用）
COOKIES_FILE = os.getenv("COOKIES_FILE", "").strip()

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


def download_video(url: str, output_dir: Path, base_name: str, cookies_file: Optional[str] = None) -> Optional[Path]:
    """
    用 yt-dlp 下载视频到 output_dir，支持 Instagram / TikTok / YouTube / YouTube Shorts 等。
    返回下载好的文件路径，失败返回 None。
    """
    out_tpl = str(output_dir / f"{base_name}.%(ext)s")
    # 不传 -f 让 yt-dlp 自动选最佳并合并，避免 "best pre-merged" 警告；YouTube 用 android 客户端缓解 403
    cmd = [
        "yt-dlp",
        "--merge-output-format", "mp4",
        "-o", out_tpl,
        "--no-part",
        "--extractor-args", "youtube:player_client=android",
        url,
    ]
    if cookies_file and os.path.isfile(cookies_file):
        cmd.extend(["--cookies", cookies_file])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"  下载失败: {result.stderr or result.stdout or ('exit ' + str(result.returncode))}")
            return None
        for f in output_dir.iterdir():
            if f.suffix.lower() in (".mp4", ".mkv", ".webm", ".m4a") and f.stem.startswith(base_name):
                return f
        mp4 = output_dir / f"{base_name}.mp4"
        return mp4 if mp4.is_file() else None
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"  下载失败: {e}")
        return None


def upload_to_drive(file_path: Path, name: str, folder_id: Optional[str]) -> Tuple[bool, Optional[str]]:
    """上传文件到 Google Drive，返回 (是否成功, Drive 链接或 None)。使用 OAuth 时占你的网盘空间。"""
    creds = get_drive_creds()
    service = build("drive", "v3", credentials=creds)
    body = {"name": name}
    if folder_id:
        body["parents"] = [folder_id]
    media = MediaFileUpload(str(file_path), resumable=True)
    try:
        result = service.files().create(body=body, media_body=media, fields="id").execute()
        file_id = result.get("id")
        link = f"https://drive.google.com/file/d/{file_id}/view" if file_id else None
        return True, link
    except Exception as e:
        print(f"  上传失败: {e}")
        return False, None


def main():
    data, sheet = get_sheet_data()
    if not data:
        print("没有可处理的链接/命名数据，请检查表格和 URL_COLUMN、NAME_COLUMN、HEADER_ROWS。")
        return
    result_col = _column_letter_to_index(RESULT_COLUMN) + 1 if RESULT_COLUMN else None  # gspread 用 1-based 列号
    print(f"共 {len(data)} 条待处理。" + (" 上传后链接将写回第 " + RESULT_COLUMN + " 列。" if result_col else ""))
    cookies = COOKIES_FILE or None
    folder_id = DRIVE_FOLDER_ID or None
    for i, (url, base_name, sheet_row) in enumerate(data, 1):
        print(f"[{i}/{len(data)}] {base_name}")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = download_video(url, Path(tmpdir), "video", cookies)
            if not tmp_path:
                continue
            final_name = base_name if base_name.endswith(tmp_path.suffix) else base_name + tmp_path.suffix
            ok, drive_link = upload_to_drive(tmp_path, final_name, folder_id)
            if ok:
                print(f"  已上传: {final_name}")
                if result_col and drive_link:
                    sheet.update_cell(sheet_row, result_col, drive_link)
                    print(f"  已写回 Drive 链接到第 {sheet_row} 行第 {RESULT_COLUMN} 列")
            else:
                print(f"  跳过上传: {final_name}")


if __name__ == "__main__":
    main()
