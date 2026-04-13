#!/usr/bin/env python3
"""
在 Google Drive 指定文件夹中查找所有 .m4a 文件，
将文件名（不含扩展名）写入同一项目配置的 Google 表格列表中。
与 main.py 共用 .env、credentials.json 和 DRIVE_FOLDER_ID。
"""

import os
import re
from typing import List, Set

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

load_dotenv()

SPREADSHEET_URL = os.getenv("SPREADSHEET_URL", "").strip()
SPREADSHEET_KEY = os.getenv("SPREADSHEET_KEY", "").strip()
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "").strip()
# 写入的工作表名称，不存在则创建
M4A_OUTPUT_SHEET = os.getenv("M4A_OUTPUT_SHEET", "m4a列表").strip()
CREDENTIALS_PATH = os.getenv("CREDENTIALS_PATH", "credentials.json")


def _extract_key_from_url(url: str) -> str:
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else ""


def _escape_drive_query(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace("'", "''")


def list_m4a_names_in_folder(service, folder_id: str) -> List[str]:
    """
    列出文件夹内所有扩展名为 .m4a 的文件，返回文件名（不含扩展名）列表，去重、排序。
    """
    safe_folder = _escape_drive_query(folder_id)
    q = f"'{safe_folder}' in parents and trashed = false"
    names: Set[str] = set()
    page_token = None
    while True:
        resp = service.files().list(
            q=q,
            fields="nextPageToken, files(name)",
            pageSize=200,
            pageToken=page_token or "",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        for f in resp.get("files") or []:
            name = (f.get("name") or "").strip()
            if name.lower().endswith(".m4a"):
                stem = name[:-4] if len(name) > 4 else name  # 去掉 .m4a
                if stem:
                    names.add(stem)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return sorted(names)


def main():
    key = SPREADSHEET_KEY or (_extract_key_from_url(SPREADSHEET_URL) if SPREADSHEET_URL else "")
    if not key:
        raise SystemExit("请设置 SPREADSHEET_URL 或 SPREADSHEET_KEY")
    if not DRIVE_FOLDER_ID:
        raise SystemExit("请设置 DRIVE_FOLDER_ID")

    creds = ServiceAccountCredentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
    drive = build("drive", "v3", credentials=creds)
    names = list_m4a_names_in_folder(drive, DRIVE_FOLDER_ID)

    print(f"在 Drive 文件夹中共找到 {len(names)} 个 .m4a 文件（已去重）。")

    gc = gspread.authorize(creds)
    workbook = gc.open_by_key(key)
    try:
        sheet = workbook.worksheet(M4A_OUTPUT_SHEET)
    except gspread.WorksheetNotFound:
        sheet = workbook.add_worksheet(title=M4A_OUTPUT_SHEET, rows=max(len(names) + 10, 100), cols=1)
        print(f"已新建工作表「{M4A_OUTPUT_SHEET}」。")

    # 第一行为表头，之后每行一个文件名（无扩展名）
    rows = [["文件名(无扩展名)"]] + [[n] for n in names]
    if rows:
        sheet.update(rows, "A1")
    print(f"已写入表格「{M4A_OUTPUT_SHEET}」A 列，共 {len(names)} 行。")


if __name__ == "__main__":
    main()
