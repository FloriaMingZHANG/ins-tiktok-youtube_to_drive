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

# 飞书多维表格（可选）：把封面图片作为「文件」上传到飞书对应记录
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "").strip()
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "").strip()
FEISHU_APP_TOKEN = os.getenv("FEISHU_APP_TOKEN", "").strip()  # 多维表格的 app_token（从多维表格 URL 取）
FEISHU_TABLE_ID = os.getenv("FEISHU_TABLE_ID", "").strip()  # 数据表 table_id
FEISHU_MATCH_FIELD = os.getenv("FEISHU_MATCH_FIELD", "").strip()  # 用于匹配行的字段名（如「文件名」），值需与表格中的命名一致
FEISHU_FILE_FIELD = os.getenv("FEISHU_FILE_FIELD", "").strip()  # 要写入封面文件的「文件」类型列名
FEISHU_DRIVE_LINK_FIELD = os.getenv("FEISHU_DRIVE_LINK_FIELD", "").strip()  # 可选：要写入视频 Drive 链接的列名
# 可选：导出目录。设置后会把封面原图 + 链接列表导出到此目录，你从本地复制到飞书即可
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
) -> Tuple[Optional[Path], Optional[Path]]:
    """
    用 yt-dlp 下载视频到 output_dir，支持 Instagram / TikTok / YouTube / YouTube Shorts 等。
    with_thumbnail=True 时同时下载封面图（与视频同目录，命名为 base_name_cover）。
    返回 (视频路径, 封面路径或 None)，失败时视频路径为 None。
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
            print(f"  下载失败: {result.stderr or result.stdout or ('exit ' + str(result.returncode))}")
            return None, None
        video_path = None
        for f in output_dir.iterdir():
            if f.suffix.lower() in (".mp4", ".mkv", ".webm", ".m4a") and f.stem.startswith(base_name) and "_cover" not in f.stem:
                video_path = f
                break
        if not video_path:
            video_path = output_dir / f"{base_name}.mp4" if (output_dir / f"{base_name}.mp4").is_file() else None
        thumb_path = None
        if with_thumbnail:
            for ext in (".jpg", ".jpeg", ".webp", ".png"):
                p = output_dir / f"{base_name}_cover{ext}"
                if p.is_file():
                    thumb_path = p
                    break
            # 若平台未提供封面（少数情况），用 ffmpeg 从视频截取一帧作为封面
            if not thumb_path and video_path:
                thumb_path = _extract_frame_as_cover(video_path, output_dir, base_name)
                if thumb_path:
                    print("  无平台封面，已从视频截取一帧作为封面")
        return video_path, thumb_path
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"  下载失败: {e}")
        return None, None


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
            video_path, thumb_path = download_video(
                url, output_dir, base_name, cookies_file, with_thumbnail=True
            )
            if video_path and video_path.is_file():
                try:
                    video_path.unlink()
                except OSError:
                    pass
            if thumb_path:
                return None, thumb_path, None
            short = "Requested format is not available" if "Requested format" in err else (
                "Only images available" if "Only images" in err else (
                    err.split("\n")[-1][:80] if err else ("exit " + str(result.returncode))
                )
            )
            print(f"  下载封面失败: {err[:200]}")
            return None, None, short
        thumb_path = None
        for ext in (".jpg", ".jpeg", ".webp", ".png"):
            p = output_dir / f"{base_name}_cover{ext}"
            if p.is_file():
                thumb_path = p
                break
        return None, thumb_path, None
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"  下载封面失败: {e}")
        return None, None, str(e)


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
    file_path: Path, name: str, folder_id: Optional[str], allow_public_view: bool = False
) -> Tuple[bool, Optional[str], Optional[str]]:
    """上传文件到 Google Drive，返回 (是否成功, 查看链接, file_id)。allow_public_view=True 时设为任何人凭链接可查看。"""
    creds = get_drive_creds()
    service = build("drive", "v3", credentials=creds)
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


def _feishu_tenant_token() -> Optional[str]:
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


def _feishu_get_field_ids(token: str) -> Optional[dict]:
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
        # 飞书返回可能在 data.items 或 data 下直接是列表
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


def _feishu_upload_media(file_path: Path, file_name: str, token: str) -> Optional[str]:
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


def _feishu_find_record_id_by_field(
    token: str, match_value: str, field_ids: dict
) -> Optional[str]:
    """列出飞书表记录，按匹配字段值找到 record_id。注意：列出记录 API 返回的 fields 以「字段名」为键，不是 field_id。"""
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
                # 列出记录接口里 fields 的键是「字段名」，不是 field_id
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


def _feishu_get_record(token: str, record_id: str, use_field_id_key: bool = True) -> Optional[dict]:
    """获取飞书单条记录的当前 fields。use_field_id_key=True 时请求返回 field_id 为键，便于与 PUT 一致。"""
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


def _feishu_update_record(
    token: str, record_id: str, file_token: str, field_ids: dict, drive_link: Optional[str] = None
) -> bool:
    """更新飞书多维表格记录：仅修改「文件」列和「Drive 链接」列，先拉取原记录再合并，避免清空匹配列等其它列。"""
    file_fid = field_ids.get(FEISHU_FILE_FIELD) if field_ids else None
    if not file_fid:
        print(f"  飞书未找到文件列「{FEISHU_FILE_FIELD}」")
        return False
    try:
        import requests
        # 必须先 GET 到当前记录再合并更新，否则不执行 PUT，避免用不完整 fields 覆盖导致其它列被清空
        record = _feishu_get_record(token, record_id)
        if record is None:
            print(f"  飞书获取记录失败，为避免覆盖其它列，跳过本次更新")
            return False
        raw_fields = record.get("fields") or {}
        # 飞书 PUT 要求 fields 的键为「字段名」。GET 可能返回 field_id 为键，需转成字段名
        id_to_name = {v: k for k, v in field_ids.items()}
        fields = {}
        for k, v in raw_fields.items():
            key_name = id_to_name.get(k) if k in id_to_name else (k if k in field_ids else k)
            fields[key_name] = v
        fields[FEISHU_FILE_FIELD] = [{"file_token": file_token}]
        link_fid = field_ids.get(FEISHU_DRIVE_LINK_FIELD) if (FEISHU_DRIVE_LINK_FIELD and field_ids) else None
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
                # 仅文件成功；再试一次：只更新链接列为纯字符串（兼容「文本」列）
                record2 = _feishu_get_record(token, record_id)
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
    failures = []  # (base_name, 原因)
    for i, (url, base_name, sheet_row) in enumerate(data, 1):
        print(f"[{i}/{len(data)}] {base_name}")
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path, thumb_path = None, None
            drive_link = ""
            if DO_VIDEO and DO_COVER:
                video_path, thumb_path = download_video(url, Path(tmpdir), "video", cookies, with_thumbnail=True)
                if not video_path:
                    failures.append((base_name, "下载视频失败"))
                    continue
                final_name = base_name if base_name.endswith(video_path.suffix) else base_name + video_path.suffix
                ok, drive_link, _ = upload_to_drive(video_path, final_name, folder_id, allow_public_view=False)
                if ok:
                    print(f"  已上传视频: {final_name}")
                    if result_col and drive_link:
                        sheet.update_cell(sheet_row, result_col, drive_link)
                else:
                    print(f"  跳过上传视频: {final_name}")
            elif DO_VIDEO:
                video_path, _ = download_video(url, Path(tmpdir), "video", cookies, with_thumbnail=False)
                if not video_path:
                    failures.append((base_name, "下载视频失败"))
                    continue
                final_name = base_name if base_name.endswith(video_path.suffix) else base_name + video_path.suffix
                ok, drive_link, _ = upload_to_drive(video_path, final_name, folder_id, allow_public_view=False)
                if ok:
                    print(f"  已上传视频: {final_name}")
                    if result_col and drive_link:
                        sheet.update_cell(sheet_row, result_col, drive_link)
                else:
                    print(f"  跳过上传视频: {final_name}")
            else:
                # 仅封面
                _, thumb_path, thumb_err = download_thumbnail_only(url, Path(tmpdir), "video", cookies)
                if not thumb_path:
                    failures.append((base_name, thumb_err or "下载封面失败"))
                    continue
                print(f"  已下载封面")
            thumb_name = (base_name + "_cover" + thumb_path.suffix) if thumb_path else None
            if thumb_path and thumb_col:
                ok_thumb, _, thumb_file_id = upload_to_drive(
                    thumb_path, thumb_name, folder_id, allow_public_view=True
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
        for name, reason in failures:
            print(f"  - {name}: {reason}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].strip().lower() in ("-h", "--help"):
        print("用法: python main.py [video|cover|both]")
        print("  video  只下载并上传视频到 Drive，写回链接")
        print("  cover  只下载封面并导出到 FEISHU_EXPORT_DIR（不下载视频）")
        print("  both   视频+封面都做（默认）")
        sys.exit(0)
    main()
