# 多平台视频：从表格批量下载并上传到 Google Drive

从 **Google 表格** 中按列读取视频链接和自定义文件名，依次下载并按命名上传到 **Google Drive**。  
**支持链接**：Instagram（含 Reels）、TikTok、YouTube、YouTube Shorts 等（由 yt-dlp 支持的平台均可）。

---

**费用说明**：本方案用到的工具均为**免费**（Python、Google 表格/Drive/Cloud 在本用途下的用量、yt-dlp 等均为免费）。  

**没有编程基础？** 请直接看 **[零基础操作指南.md](./零基础操作指南.md)**，里面有从安装 Python 到运行脚本的详细步骤说明。

**要打包发给别人用（Windows / Mac 通用）？** 看 **[分发说明.md](./分发说明.md)**，按说明打包并让对方按《零基础操作指南》做一次配置即可。

## 流程概览

1. 读取 Google 表格：一列放视频链接（Ins / TikTok / YouTube / Shorts 等），一列放要命名的文件名  
2. 用 **yt-dlp** 按链接顺序下载视频（自动识别平台）  
3. 用另一列的名称保存并上传到 Google Drive（可选指定文件夹）

## 环境准备

### 1. Python 与依赖

```bash
cd ins_to_drive
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Google 云端凭证（服务账号）

- 打开 [Google Cloud Console](https://console.cloud.google.com/)
- 创建或选择项目 → **API 和服务** → **启用 API**：启用 **Google Sheets API** 和 **Google Drive API**
- **凭据** → **创建凭据** → **服务账号** → 创建后为该账号创建 **密钥（JSON）**
- 将下载的 JSON 放到本项目目录，命名为 `credentials.json`（或通过环境变量 `CREDENTIALS_PATH` 指定路径）

**重要**：  
- 把要读取的 **Google 表格** 共享给该服务账号的邮箱（在 JSON 里可看到 `client_email`），权限至少为「查看者」。  
- 若需上传到某个 **Drive 文件夹**，把该文件夹也共享给同一服务账号邮箱，权限至少为「编辑者」。

### 3. 配置表格与列

- 表格中：**一列** 放视频链接（Instagram / TikTok / YouTube / YouTube Shorts 等），**另一列** 放要保存的文件名（不含扩展名也可，脚本会加 `.mp4`）。
- 复制 `config.example.env` 为 `.env`，在 `.env` 里填写：

| 变量 | 说明 |
|------|------|
| `SPREADSHEET_URL` 或 `SPREADSHEET_KEY` | 表格完整 URL，或从 URL 里 `/d/xxx/` 取出的表格 ID |
| `SHEET_NAME` | 工作表名称（左下角标签）；留空则用第一个表 |
| `URL_COLUMN` | 链接所在列字母，如 `A` |
| `NAME_COLUMN` | 文件名所在列字母，如 `B` |
| `HEADER_ROWS` | 表头行数，数据从下一行开始，默认 `1` |
| `RESULT_COLUMN` | 视频 Drive 链接写回的列（如 C） |
| `THUMBNAIL_COLUMN` | 封面图写回的列（如 D）；留空则不下载封面。该列写入 **=IMAGE(直接地址)**，单元格内**显示图片**而非纯链接；导到飞书多维表格时可用该直接地址（见下方说明）。若无平台封面则用 ffmpeg 截一帧（需本机已装 ffmpeg） |
| `DRIVE_FOLDER_ID` | 可选。上传到的 Drive 文件夹 ID（浏览器打开文件夹时 URL 里 `/folders/` 后面的那串） |
| `DO_VIDEO` | 默认 `1`。为 `0` 时本次不下载/上传视频，只做封面（若 DO_COVER=1） |
| `DO_COVER` | 默认 `1`。为 `0` 时本次不下载/导出封面，只做视频。可组合：只做视频、只做封面、或两个都做 |
| `COOKIES_FILE` | 可选。Instagram 的 cookies 文件路径，若下载被限流可导出浏览器 cookies 再试 |

### 4. Instagram 下载说明

- 脚本通过 **yt-dlp** 下载，`pip install -r requirements.txt` 已包含；也可单独安装：`pip install yt-dlp` 或 `brew install yt-dlp`。
- 若出现无法解析链接、限流等，可尝试：
  - 使用最新版：`yt-dlp -U`
  - 设置 `COOKIES_FILE`，使用从浏览器导出的 Instagram cookies 文件

## 运行

```bash
python main.py
```

脚本会按行顺序：读表 → 下载每条 Ins 链接 → 以对应列命名并上传到 Drive（若配置了 `DRIVE_FOLDER_ID` 则上传到该文件夹）。

## 目录结构示例

```
ins_to_drive/
├── main.py              # 主脚本
├── requirements.txt
├── config.example.env   # 配置示例
├── .env                 # 你的配置（勿提交）
├── credentials.json     # 服务账号密钥（勿提交）
└── README.md
```

## 飞书多维表格「文件」列（封面以文件形式写入）

若飞书多维表格里有一列类型为「**文件**」，需要把封面**图片文件**上传到该列（而非仅链接）：

1. 在 [飞书开放平台](https://open.feishu.cn/) 创建应用，开通权限：**查看、评论、编辑和管理多维表格**、**上传下载云文档**（或驱动相关权限）。
2. **把应用加到多维表格**（否则接口会返回 403 / 91403 Forbidden）：
   - 用**浏览器**打开该多维表格（飞书网页版 feishu.cn），不要用桌面客户端。
   - 点击右上角 **「…」**（三个点）→ 选 **「更多」** → 在列表里找 **「添加文档应用」** 或 **「添加应用」** → 搜索你的自建应用并添加。
   - 若菜单里没有「添加文档应用」，请用**文档所有者**或**有分享/管理权限**的账号操作，或联系管理员；部分版本该入口仅在网页版显示。
3. 获取 **app_id**、**app_secret**；从多维表格 URL 获取 **app_token**（如 `https://xxx.feishu.cn/base/AppToken?table=TableId` 中的 `AppToken`）和 **table_id**（数据表 ID）。
4. 在 `.env` 中填写：
   - `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_APP_TOKEN`、`FEISHU_TABLE_ID`
   - `FEISHU_MATCH_FIELD`：飞书中用于**匹配当前行**的字段名（如「文件名」），其值需与 Google 表格里的「命名」列一致，脚本会按此找到对应记录。
   - `FEISHU_FILE_FIELD`：要写入封面文件的「**文件**」类型列名（如「封面」）。
5. 运行脚本后，封面会先上传到 Drive 并写回 Google 表格；若上述飞书配置完整，会**同时**把封面图片上传到飞书并写入对应记录的「文件」列。

Google 表格中的封面列仍是 **=IMAGE(...)** 显示图片；飞书侧是真正的**文件附件**。

### 若直接写飞书失败：用「导出包」再推送到飞书

Sheet 里是图片公式不是原图，无法直接复制到飞书。若 main.py 写飞书报错，可用「先导出、再推送」：

1. 在 `.env` 里增加一行：**`FEISHU_EXPORT_DIR=feishu_export`**（或任意目录名）。
2. 照常运行 **`python main.py`**。脚本会把每条**封面原图**保存到 `feishu_export/covers/`，并把「命名、视频 Drive 链接、封面文件名」追加到 `feishu_export/links.csv`。
3. 再运行 **`python push_export_to_feishu.py`**，会按 CSV 逐行：上传封面到飞书、按「命名」找到对应记录、写入「文件」列和「链接」列。

这样你本地始终有一份**封面原图 + 链接表**，可随时重跑推送脚本，或手动在飞书里对照 CSV 上传。

## 常见问题

- **无法打开表格**：确认已把表格共享给 `credentials.json` 里 `client_email` 的邮箱。  
- **无法上传到文件夹**：确认该 Drive 文件夹已共享给同一服务账号邮箱且权限足够。  
- **表格里封面不显示**：检查 Drive 里对应封面文件是否已设为「知道链接的任何人可查看」。  
- **下载失败**：先单独用 `yt-dlp "链接"` 测试；Ins/TikTok 等若需登录，配置 `COOKIES_FILE` 并保持 yt-dlp 更新（`yt-dlp -U`）。
