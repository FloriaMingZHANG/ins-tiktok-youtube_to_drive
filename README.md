# 视频批量下载 → Google Drive

从 Google 表格读取视频链接和文件名，批量下载并上传到 Google Drive，支持写回链接和封面图。

**支持平台**：Instagram（含 Reels）、**X (Twitter)**、TikTok、YouTube、YouTube Shorts、**小红书**等所有 yt-dlp 支持的平台。画质优先原画/最高可用（X 建议配置 cookie 以获取高清）。

**支持系统**：Mac / Windows（v0.3.0 起新增 Windows 一键配置，详见 [RELEASE_NOTES_v0.3.0.md](RELEASE_NOTES_v0.3.0.md)）

---

## 快速开始

### 1. 安装依赖

**Windows（推荐）**：双击运行 `setup_windows.bat` 完成一键配置。

**Mac / 手动安装**：

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows CMD: .venv\Scripts\activate.bat   # PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. 配置 Google 凭证

1. 打开 [Google Cloud Console](https://console.cloud.google.com/)，启用 **Google Sheets API** 和 **Google Drive API**
2. 创建**服务账号**，下载密钥 JSON，重命名为 `credentials.json` 放到项目目录
3. 将 Google 表格和目标 Drive 文件夹共享给 `credentials.json` 里的 `client_email`（表格「查看者」权限，文件夹「编辑者」权限）

### 3. 配置 .env

```bash
cp config.example.env .env
```

编辑 `.env`，至少填写以下几项：

| 变量 | 说明 |
|------|------|
| `SPREADSHEET_URL` | Google 表格完整 URL |
| `URL_COLUMN` | 视频链接所在列，如 `A` |
| `NAME_COLUMN` | 文件名所在列，如 `B` |
| `RESULT_COLUMN` | 视频 Drive 链接写回的列，如 `C` |
| `DRIVE_FOLDER_ID` | 上传目标文件夹 ID（Drive URL 中 `/folders/` 后的部分） |

### 4. 运行

```bash
python main.py          # 视频+封面都做（默认）
python main.py video    # 只下载上传视频
python main.py cover    # 只抓封面
```

---

## 按名称批量填充 Drive 链接

若表格里已有「视频名称」列，而视频已存在于同一 Drive 文件夹中（例如由 `main.py` 上传过），只需按名称查找到文件并把链接写回表格，可运行：

```bash
python fill_drive_links.py
```

- **共用配置**：使用与 `main.py` 相同的 `.env` 和 `credentials.json`，以及同一个 **`DRIVE_FOLDER_ID`**（Drive 文件夹）。
- **表格列**：从 `NAME_COLUMN`（如 `B`）读取视频名称，将找到的 Drive 链接写入 `RESULT_COLUMN`（如 `C`）。
- **匹配规则**：在指定文件夹内按**文件名精确匹配**；若名称无扩展名，会自动尝试 `.mp4`、`.mov`、`.avi` 等常见视频扩展名。
- **权限**：需要 **Drive API 只读**（列出文件夹内文件）。若服务账号此前只开了「Drive 文件」权限，需在 Cloud Console 为该服务账号密钥勾选「查看和管理 Google Drive 中的文件」或至少「查看 Google Drive 中的文件」。

---

## 封面图

设置 `THUMBNAIL_COLUMN=D` 后，脚本会下载封面并在表格中用 `=IMAGE()` 公式直接显示图片。若平台无封面，自动用 ffmpeg 从视频截取第 1 秒作为封面（需本机已安装 ffmpeg）。

---

## 飞书多维表格集成（可选）

若需要将封面作为**文件附件**写入飞书多维表格：

1. 在[飞书开放平台](https://open.feishu.cn/)创建应用，开通多维表格权限
2. 用**网页版**打开多维表格 → 右上角「…」→「更多」→「添加文档应用」，添加你的应用
3. 在 `.env` 中填写 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_APP_TOKEN`、`FEISHU_TABLE_ID`、`FEISHU_MATCH_FIELD`（匹配列名）、`FEISHU_FILE_FIELD`（文件列名）

如果直接写飞书失败，可改用两步方案：设置 `FEISHU_EXPORT_DIR=feishu_export` 后运行 `main.py`，封面原图会导出到本地，再运行 `push_export_to_feishu.py` 补推。

---

## 其他配置

- **需要登录的平台**（如 Instagram、X (Twitter)）：设置 `COOKIES_FILE=cookies.txt`，在对应站点登录后导出浏览器 cookies 填入路径；X 反爬较严，建议用 cookie 以稳定下载高清
- **上传到个人网盘根目录**：提供 `client_secret.json`（OAuth），首次运行会弹出浏览器授权
- **只做封面不上传 Drive**：设置 `SKIP_DRIVE_COVER=1` 配合 `FEISHU_EXPORT_DIR` 使用

---

## 目录结构

```
├── main.py                # 主脚本（下载+上传+写回链接）
├── fill_drive_links.py    # 按表格中的视频名称在 Drive 文件夹中查找并写回链接
├── push_export_to_feishu.py  # 飞书补推脚本
├── requirements.txt
├── config_example.env     # 配置示例
├── .env                   # 你的配置（勿提交）
└── credentials.json       # 服务账号密钥（勿提交）
```

## 常见问题

- **无法读取表格**：确认已将表格共享给 `credentials.json` 里的 `client_email`
- **上传失败**：确认 Drive 文件夹已共享给同一邮箱且权限为「编辑者」
- **封面不显示**：检查 Drive 中该文件是否设为「知道链接的任何人可查看」
- **下载失败**：用 `yt-dlp "链接"` 单独测试；如需登录则配置 `COOKIES_FILE` 并更新 yt-dlp（`yt-dlp -U`）
- **小红书链接**：支持 `xiaohongshu.com/explore/xxx`；短链 `xhslink.com` 会跳转，若失败可手动展开后粘贴
- **飞书 403/91403**：应用未被添加到该多维表格，按上方步骤在网页版添加
- **fill_drive_links.py 报 403**：确认 Google Cloud 项目已启用 Drive API，且目标文件夹已共享给 `credentials.json` 中的 `client_email`（至少「查看者」）
