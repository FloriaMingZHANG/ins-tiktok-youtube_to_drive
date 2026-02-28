#!/usr/bin/env python3
"""飞书多维表格 API：token、字段列表、上传素材、查找记录、更新记录。供 push_export_to_feishu 等脚本调用。"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "").strip()
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "").strip()
FEISHU_APP_TOKEN = os.getenv("FEISHU_APP_TOKEN", "").strip()
FEISHU_TABLE_ID = os.getenv("FEISHU_TABLE_ID", "").strip()
FEISHU_MATCH_FIELD = os.getenv("FEISHU_MATCH_FIELD", "").strip()
FEISHU_FILE_FIELD = os.getenv("FEISHU_FILE_FIELD", "").strip()
FEISHU_DRIVE_LINK_FIELD = os.getenv("FEISHU_DRIVE_LINK_FIELD", "").strip()


def feishu_tenant_token() -> Optional[str]:
    """获取飞书 tenant_access_token。"""
    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        return None
    try:
        import requests
        r = requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
            timeout=10,
        )
        d = r.json()
        if d.get("code") == 0:
            return d.get("tenant_access_token")
    except Exception:
        pass
    return None


def feishu_get_field_ids(token: str) -> Optional[dict]:
    """获取飞书表字段名 -> field_id 映射（API 用 field_id 作为键）。"""
    try:
        import requests
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{FEISHU_TABLE_ID}/fields"
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
        d = r.json() if r.text else {}
        if r.status_code != 200:
            print(f"  飞书获取字段列表 HTTP {r.status_code}: {r.text[:300]}")
            if r.status_code == 403 and "91403" in (r.text or ""):
                print("  提示：403/91403 表示应用无权访问该多维表格。请用浏览器打开该多维表格（飞书网页版）→ 右上角「…」→「更多」→ 找「添加文档应用」或「添加应用」→ 搜索并添加你的自建应用。若无该选项，请用文档所有者账号操作或联系管理员。")
            return None
        if d.get("code") != 0:
            print(f"  飞书获取字段列表失败: code={d.get('code')} msg={d.get('msg', '')}")
            return None
        data = d.get("data") or {}
        items = data.get("items") if isinstance(data.get("items"), list) else (data if isinstance(data, list) else [])
        if not items and isinstance(data, dict):
            items = data.get("fields") or []
        result = {}
        for f in items:
            if isinstance(f, dict) and f.get("field_id"):
                name = f.get("name") or f.get("field_name")
                if name:
                    result[name] = f["field_id"]
        if not result:
            print(f"  飞书获取字段列表为空或格式异常，原始 data 键: {list(data.keys()) if isinstance(data, dict) else 'list'}")
            return None
        return result
    except Exception as e:
        print(f"  飞书获取字段列表异常: {e}")
        return None


def feishu_upload_media(file_path: Path, file_name: str, token: str) -> Optional[str]:
    """上传文件到飞书多维表格素材，返回 file_token。"""
    try:
        import requests
        url = "https://open.feishu.cn/open-apis/drive/v1/medias/upload_all"
        size = file_path.stat().st_size
        with open(file_path, "rb") as f:
            file_bytes = f.read()
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            data={
                "file_name": file_name,
                "parent_type": "bitable_file",
                "parent_node": FEISHU_APP_TOKEN,
                "size": str(size),
            },
            files={"file": (file_name, file_bytes, "application/octet-stream")},
            timeout=30,
        )
        if r.status_code != 200:
            print(f"  飞书上传封面 HTTP {r.status_code}: {r.text[:200]}")
            return None
        d = r.json()
        if d.get("code") != 0:
            print(f"  飞书上传封面失败: code={d.get('code')} msg={d.get('msg', '')}")
            return None
        return d.get("data", {}).get("file_token")
    except Exception as e:
        print(f"  飞书上传封面异常: {e}")
        return None


def feishu_find_record_id_by_field(
    token: str, match_value: str, field_ids: dict
) -> Optional[str]:
    """列出飞书表记录，按匹配字段值找到 record_id。"""
    if not field_ids or FEISHU_MATCH_FIELD not in field_ids:
        print(f"  飞书未找到匹配列「{FEISHU_MATCH_FIELD}」，请检查列名与 .env 一致")
        return None
    try:
        import requests
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{FEISHU_TABLE_ID}/records"
        page_token = None
        match_value_stripped = (match_value or "").strip()
        for _ in range(100):
            params = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token
            r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=15)
            if r.status_code != 200:
                print(f"  飞书列出记录失败 HTTP {r.status_code}")
                return None
            d = r.json()
            if d.get("code") != 0:
                print(f"  飞书列出记录失败: code={d.get('code')} msg={d.get('msg', '')}")
                return None
            for rec in (d.get("data") or {}).get("items") or []:
                fields = rec.get("fields") or {}
                val = fields.get(FEISHU_MATCH_FIELD)
                if val is None:
                    continue
                if isinstance(val, list) and len(val) and isinstance(val[0], dict):
                    val = (val[0].get("text") or val[0].get("link") or "").strip()
                elif isinstance(val, str):
                    val = val.strip()
                else:
                    val = str(val).strip()
                if val == match_value_stripped:
                    return rec.get("record_id")
            page_token = (d.get("data") or {}).get("page_token")
            if not page_token:
                break
        return None
    except Exception as e:
        print(f"  飞书查找记录异常: {e}")
        return None


def feishu_get_record(token: str, record_id: str, use_field_id_key: bool = True) -> Optional[dict]:
    """获取飞书单条记录的当前 fields。"""
    try:
        import requests
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{FEISHU_TABLE_ID}/records/{record_id}"
        params = {"user_field_key": "field_id"} if use_field_id_key else {}
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=15)
        if r.status_code != 200:
            return None
        d = r.json()
        if d.get("code") != 0:
            return None
        data = d.get("data") or {}
        return data.get("record") or data
    except Exception:
        return None


def feishu_update_record(
    token: str, record_id: str, file_token: str, field_ids: dict, drive_link: Optional[str] = None
) -> bool:
    """更新飞书多维表格记录：仅修改「文件」列和「Drive 链接」列，先拉取原记录再合并。"""
    file_fid = field_ids.get(FEISHU_FILE_FIELD) if field_ids else None
    if not file_fid:
        print(f"  飞书未找到文件列「{FEISHU_FILE_FIELD}」")
        return False
    try:
        import requests
        record = feishu_get_record(token, record_id)
        if record is None:
            print(f"  飞书获取记录失败，为避免覆盖其它列，跳过本次更新")
            return False
        raw_fields = record.get("fields") or {}
        id_to_name = {v: k for k, v in field_ids.items()}
        fields = {}
        for k, v in raw_fields.items():
            key_name = id_to_name.get(k) if k in id_to_name else (k if k in field_ids else k)
            fields[key_name] = v
        fields[FEISHU_FILE_FIELD] = [{"file_token": file_token}]
        if FEISHU_DRIVE_LINK_FIELD and drive_link:
            fields[FEISHU_DRIVE_LINK_FIELD] = {"link": drive_link, "text": drive_link}
        print(f"  飞书本次写入列：文件列「{FEISHU_FILE_FIELD}」、链接列「{FEISHU_DRIVE_LINK_FIELD or '(未配置)'}」")
        api_url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}/tables/{FEISHU_TABLE_ID}/records/{record_id}"
        r = requests.put(
            api_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"fields": fields},
            timeout=15,
        )
        if r.status_code != 200:
            print(f"  飞书更新记录 HTTP {r.status_code}: {r.text[:200]}")
            return False
        d = r.json()
        if d.get("code") == 1254067 and FEISHU_DRIVE_LINK_FIELD and drive_link:
            print(f"  飞书 1254067：链接列「{FEISHU_DRIVE_LINK_FIELD}」写入失败，正在重试：先仅写文件列…")
            del fields[FEISHU_DRIVE_LINK_FIELD]
            r2 = requests.put(
                api_url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"fields": fields},
                timeout=15,
            )
            if r2.status_code == 200 and (r2.json() or {}).get("code") == 0:
                record2 = feishu_get_record(token, record_id)
                if record2:
                    raw2 = record2.get("fields") or {}
                    fields2 = {}
                    for k, v in raw2.items():
                        key_name = id_to_name.get(k) if k in id_to_name else (k if k in field_ids else k)
                        fields2[key_name] = v
                    fields2[FEISHU_DRIVE_LINK_FIELD] = drive_link
                    r3 = requests.put(
                        api_url,
                        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                        json={"fields": fields2},
                        timeout=15,
                    )
                    if r3.status_code == 200 and (r3.json() or {}).get("code") == 0:
                        print(f"  已写入飞书：封面 + Drive 链接（链接列以纯文本写入）")
                        return True
                print(f"  已写入飞书：封面（链接列「{FEISHU_DRIVE_LINK_FIELD}」未写入，请检查该列在飞表中的类型是否为「超链接」或「文本」）")
                return True
            print(f"  飞书更新记录失败: code={d.get('code')} msg={d.get('msg', '')}")
            return False
        if d.get("code") != 0:
            print(f"  飞书更新记录失败: code={d.get('code')} msg={d.get('msg', '')}")
            return False
        return True
    except Exception as e:
        print(f"  飞书更新记录异常: {e}")
        return False
