#!/usr/bin/env python3
"""
读取「m4a列表」工作表中的名称，检查 Sheet1 的 A 列：
若某行 A 列的值在 m4a 列表中，则将该行标色（浅黄）。
与 main.py 共用 .env、credentials.json。
"""

import os
import re
from typing import Set

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from gspread_formatting import cellFormat, color, format_cell_range

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]

load_dotenv()

SPREADSHEET_URL = os.getenv("SPREADSHEET_URL", "").strip()
SPREADSHEET_KEY = os.getenv("SPREADSHEET_KEY", "").strip()
# 存放 m4a 文件名（无扩展名）的工作表名
M4A_OUTPUT_SHEET = os.getenv("M4A_OUTPUT_SHEET", "m4a列表").strip()
# 要检查并标色的工作表：留空为第一个工作表（Sheet1）
SHEET_TO_CHECK = os.getenv("SHEET_TO_CHECK", "").strip()
CREDENTIALS_PATH = os.getenv("CREDENTIALS_PATH", "credentials.json")

# 匹配时标色：浅黄
HIGHLIGHT_COLOR = color(1.0, 0.95, 0.7)


def _extract_key_from_url(url: str) -> str:
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else ""


def get_m4a_names_set(workbook) -> Set[str]:
    """从「m4a列表」表 A 列读取名称（跳过第 1 行表头），返回集合。"""
    try:
        sheet = workbook.worksheet(M4A_OUTPUT_SHEET)
    except gspread.WorksheetNotFound:
        raise SystemExit(f"未找到工作表「{M4A_OUTPUT_SHEET}」，请先运行 list_m4a_to_sheet.py 生成 m4a 列表。")
    col_a = sheet.col_values(1)
    if not col_a:
        return set()
    # 第 1 行为表头，从第 2 行起为名称
    names = set()
    for cell in col_a[1:]:
        s = (cell or "").strip()
        if s:
            names.add(s)
    return names


def main():
    key = SPREADSHEET_KEY or (_extract_key_from_url(SPREADSHEET_URL) if SPREADSHEET_URL else "")
    if not key:
        raise SystemExit("请设置 SPREADSHEET_URL 或 SPREADSHEET_KEY")

    creds = ServiceAccountCredentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    workbook = gc.open_by_key(key)
    m4a_set = get_m4a_names_set(workbook)
    if not m4a_set:
        print("m4a 列表为空，无需标色。")
        return

    if SHEET_TO_CHECK:
        sheet = workbook.worksheet(SHEET_TO_CHECK)
    else:
        sheet = workbook.sheet1
    sheet_name = sheet.title
    col_a = sheet.col_values(1)
    if not col_a:
        print("Sheet1 A 列为空。")
        return

    fmt = cellFormat(backgroundColor=HIGHLIGHT_COLOR)
    highlighted = 0
    for i, cell in enumerate(col_a):
        row_1based = i + 1
        val = (cell or "").strip()
        if val and val in m4a_set:
            format_cell_range(sheet, f"{row_1based}:{row_1based}", fmt)
            highlighted += 1

    print(f"已在工作表「{sheet_name}」中为 A 列出现在 m4a 列表的 {highlighted} 行标色（浅黄）。")


if __name__ == "__main__":
    main()
