#!/usr/bin/env python3
"""
从 Google 表格读取「视频名称」列，在已配置的 Drive 文件夹中查找文件名包含该名称的文件，
将 Drive 链接批量写回表格指定列。与 main.py 共用 .env 和同一 Drive 文件夹。
匹配规则：Drive 文件名包含表格里的名称即视为匹配（如表格「视频1」可匹配「视频1.mp4」「视频1_最终版.mp4」）。
"""

import os
import re
from typing import List, Optional, Tuple

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import build

# 读表格 + 只读 Drive（在文件夹里按名称查文件）
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

load_dotenv()

SPREADSHEET_URL = os.getenv("SPREADSHEET_URL", "").strip()
SPREADSHEET_KEY = os.getenv("SPREADSHEET_KEY", "").strip()
SHEET_NAME = os.getenv("SHEET_NAME", "").strip()
NAME_COLUMN = os.getenv("NAME_COLUMN", "B").strip().upper()
HEADER_ROWS = int(os.getenv("HEADER_ROWS", "1"))
RESULT_COLUMN = os.getenv("RESULT_COLUMN", "C").strip().upper()
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "").strip()
CREDENTIALS_PATH = os.getenv("CREDENTIALS_PATH", "credentials.json")

def _column_letter_to_index(col: str) -> int:
    """A->0, B->1, ..."""
    i = 0
    for c in col:
        i = i * 26 + (ord(c) - ord("A") + 1)
    return i - 1


def _extract_key_from_url(url: str) -> str:
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else ""


def _escape_drive_query(s: str) -> str:
    """Drive API q 参数中单引号需双写。"""
    return (s or "").replace("\\", "\\\\").replace("'", "''")


def get_sheet_name_column(sheet) -> List[Tuple[str, int]]:
    """返回 (视频名称, 行号 1-based) 列表，跳过空名称。"""
    name_col = _column_letter_to_index(NAME_COLUMN)
    all_rows = sheet.get_all_values()
    data = []
    for idx, row in enumerate(all_rows[HEADER_ROWS:]):
        if len(row) <= name_col:
            continue
        name = (row[name_col] or "").strip()
        if not name:
            continue
        sheet_row_1based = HEADER_ROWS + idx + 1
        data.append((name, sheet_row_1based))
    return data


def find_file_id_in_folder(service, folder_id: str, name: str) -> Optional[str]:
    """
    在指定 Drive 文件夹中查找文件名包含 name 的文件（包含即匹配）。
    如表格里是「视频1」，则「视频1.mp4」「视频1_最终版」等都会匹配，取第一个。
    返回第一个匹配的 file id，未找到返回 None。
    """
    if not name or not name.strip():
        return None
    safe_name = _escape_drive_query(name.strip())
    safe_folder = _escape_drive_query(folder_id)
    q = f"'{safe_folder}' in parents and name contains '{safe_name}' and trashed = false"
    try:
        resp = service.files().list(
            q=q,
            fields="files(id)",
            pageSize=1,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files = resp.get("files") or []
        return files[0]["id"] if files else None
    except Exception:
        return None


def main():
    key = SPREADSHEET_KEY or (_extract_key_from_url(SPREADSHEET_URL) if SPREADSHEET_URL else "")
    if not key:
        raise SystemExit("请设置 SPREADSHEET_URL 或 SPREADSHEET_KEY")
    if not DRIVE_FOLDER_ID:
        raise SystemExit("请设置 DRIVE_FOLDER_ID（与 main.py 使用的 Drive 文件夹一致）")
    if not RESULT_COLUMN:
        raise SystemExit("请设置 RESULT_COLUMN（如 C），用于写回 Drive 链接")

    creds = ServiceAccountCredentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    workbook = gc.open_by_key(key)
    sheet = workbook.worksheet(SHEET_NAME) if SHEET_NAME else workbook.sheet1

    name_rows = get_sheet_name_column(sheet)
    if not name_rows:
        print("表格中未找到视频名称数据，请检查 NAME_COLUMN 和 HEADER_ROWS。")
        return

    drive = build("drive", "v3", credentials=creds)
    result_col_index = _column_letter_to_index(RESULT_COLUMN)

    # 为每行查 Drive 并收集 (行号, 链接)
    updates: List[Tuple[int, str]] = []
    not_found: List[str] = []
    for name, row_1 in name_rows:
        file_id = find_file_id_in_folder(drive, DRIVE_FOLDER_ID, name)
        if file_id:
            link = f"https://drive.google.com/file/d/{file_id}/view"
            updates.append((row_1, link))
        else:
            not_found.append(name)

    if not updates:
        print("未在 Drive 文件夹中找到任何匹配文件。请确认 DRIVE_FOLDER_ID 与视频所在文件夹一致，且名称一致。")
        if not_found:
            print("未匹配的名称示例：", not_found[:5])
        return

    # 批量写回：按行号排序后一次性更新范围，减少 API 调用
    updates.sort(key=lambda x: x[0])
    result_col_1 = result_col_index + 1
    for row_1, link in updates:
        sheet.update_cell(row_1, result_col_1, link)

    print(f"共 {len(name_rows)} 行名称，已填写 Drive 链接 {len(updates)} 行到第 {RESULT_COLUMN} 列。")
    if not_found:
        print(f"未找到匹配文件的 {len(not_found)} 行：")
        for n in not_found[:20]:
            print(f"  - {n}")
        if len(not_found) > 20:
            print(f"  ... 等共 {len(not_found)} 个")


if __name__ == "__main__":
    main()
