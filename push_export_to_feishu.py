#!/usr/bin/env python3
"""
读取 main.py 导出的「飞书导出包」（feishu_export/covers/ + links.csv），
按行上传封面到飞书并写入「文件」列和「链接」列。适合直接写飞书失败时，用「先导出再推送」的方式补写。
用法：在 ins_to_drive 目录下执行  python push_export_to_feishu.py
"""
import csv
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import feishu

FEISHU_EXPORT_DIR = os.getenv("FEISHU_EXPORT_DIR", "").strip() or "feishu_export"
FEISHU_MATCH_FIELD = feishu.FEISHU_MATCH_FIELD
FEISHU_DRIVE_LINK_FIELD = feishu.FEISHU_DRIVE_LINK_FIELD


def run():
    export_root = Path(FEISHU_EXPORT_DIR).expanduser().resolve()
    csv_path = export_root / "links.csv"
    covers_dir = export_root / "covers"
    if not csv_path.is_file():
        print(f"未找到 {csv_path}，请先运行 main.py 并设置 .env 中 FEISHU_EXPORT_DIR（如 feishu_export）以导出封面和链接。")
        sys.exit(1)
    if not covers_dir.is_dir():
        print(f"未找到目录 {covers_dir}")
        sys.exit(1)

    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        r = csv.reader(f)
        header = next(r, None)
        for row in r:
            if len(row) >= 3:
                rows.append({"match": row[0].strip(), "drive_link": row[1].strip(), "cover_file": row[2].strip()})
            elif len(row) >= 2:
                rows.append({"match": row[0].strip(), "drive_link": row[1].strip(), "cover_file": ""})

    if not rows:
        print("links.csv 中没有数据行。")
        sys.exit(0)

    token = feishu.feishu_tenant_token()
    if not token:
        print("飞书 token 获取失败，请检查 .env 中 FEISHU_APP_ID、FEISHU_APP_SECRET。")
        sys.exit(1)
    field_ids = feishu.feishu_get_field_ids(token)
    if not field_ids:
        print("飞书获取字段列表失败。")
        sys.exit(1)

    ok, skip, fail = 0, 0, 0
    for i, row in enumerate(rows, 1):
        name, drive_link, cover_file = row["match"], row["drive_link"], row["cover_file"]
        print(f"[{i}/{len(rows)}] {name}")
        cover_path = (covers_dir / cover_file) if cover_file else None
        if not cover_path or not cover_path.is_file():
            print(f"  跳过：封面文件不存在 {cover_path}")
            skip += 1
            continue
        ftok = feishu.feishu_upload_media(cover_path, cover_file, token)
        if not ftok:
            print(f"  上传封面失败")
            fail += 1
            continue
        rid = feishu.feishu_find_record_id_by_field(token, name, field_ids)
        if not rid:
            print(f"  未找到匹配记录（飞表「{FEISHU_MATCH_FIELD}」列需有值 {name}）")
            fail += 1
            continue
        if feishu.feishu_update_record(token, rid, ftok, field_ids, drive_link=drive_link):
            print(f"  已写入飞书")
            ok += 1
        else:
            fail += 1

    print(f"\n完成：成功 {ok}，跳过 {skip}，失败 {fail}。")


if __name__ == "__main__":
    run()
