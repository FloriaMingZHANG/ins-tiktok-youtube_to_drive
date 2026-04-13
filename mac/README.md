# Mac 使用说明

**完整步骤教程**（从安装到每次怎么跑）：请打开 **[运行教程.md](运行教程.md)**。

核心代码已集中在 **`mac/app/`**，请在 **`mac/app/`** 内修改 Python 与配置；本目录提供一键脚本与说明。仓库根目录保留 Windows 脚本与另一套副本，二者可独立演进。

## 用 Cursor 打开

- **只搞 Mac**：**文件 → 打开文件夹…** → 选 `ins_to_drive/mac/app`（工作区即 `main.py` 所在目录）。
- **整仓一起开**：打开 `ins_to_drive`，在侧栏中主要编辑 `mac/app/` 即可。

## 环境（虚拟环境在 `mac/app/.venv`）

```bash
bash /path/to/ins_to_drive/mac/setup_mac.sh
```

依赖：**Python 3**；封面截帧需要 **`brew install ffmpeg`**。

## 凭证与配置为什么要放在 `mac/app/`？

程序在终端里运行时，**当前工作目录**默认是 `mac/app/`（你用 `cd .../mac/app` 或 `run_main.sh` 时就是这样）。  
`main.py` 会**优先在当前目录**找 `credentials.json`、`.env`，以及 `.env` 里写的 `COOKIES_FILE=cookies.txt` 这类**相对路径**——所以这些文件要和 `main.py` 放在**同一层**，也就是 **`mac/app/`**。

---

## 一步到位（推荐）：从仓库根目录自动复制

若你以前在 **仓库根目录**（和根目录 `main.py` 同级）已经有过 `credentials.json`、`.env`、`cookies.txt` 等，在终端执行（把路径换成你的实际路径）：

```bash
bash "/Users/floriazhang/Library/CloudStorage/OneDrive-bfsu.edu.cn/cursor/ins_to_drive/mac/sync_secrets_to_app.sh"
```

脚本会把**根目录里已经存在的**下列文件复制到 `mac/app/`（没有的会跳过并提示）：

| 文件 | 是否常见 |
|------|----------|
| `credentials.json` | **几乎必需**（Google 服务账号密钥） |
| `.env` | **必需**（表格 URL、列名、Drive 文件夹等） |
| `cookies.txt` | **按需**（下载 Ins / X 等需登录时，且 `.env` 里写了 `COOKIES_FILE=cookies.txt`） |
| `client_secret.json` | **按需**（用 OAuth 上传到你个人网盘时） |
| `token.json` | **按需**（OAuth 授权后生成） |

复制完成后，若你**从来没有** `.env`，再在 `mac/app` 里补一份模板：

```bash
cd "/Users/floriazhang/Library/CloudStorage/OneDrive-bfsu.edu.cn/cursor/ins_to_drive/mac/app"
cp -n config.example.env .env
```

`-n` 表示：若已有 `.env`（例如刚被脚本复制过来）则**不覆盖**。

---

## 手动操作（和「复制脚本」二选一）

1. **credentials.json**  
   Google Cloud 下载的服务账号密钥，改名为 `credentials.json`，放到文件夹：

   `.../ins_to_drive/mac/app/credentials.json`

2. **.env**  
   在 `mac/app` 里执行 `cp config.example.env .env`，用文本编辑器打开 `mac/app/.env` 填好表格与 Drive 等变量（说明见仓库根目录 **README.md**）。

3. **cookies.txt（按需）**  
   只有当你用 **文件方式** 给 yt-dlp 传 Cookie 时才需要：把导出的 Netscape 格式文件放到 `mac/app/cookies.txt`，并在 `mac/app/.env` 里写：

   `COOKIES_FILE=cookies.txt`  

   若你用的是 **浏览器直读**（`.env` 里 `COOKIES_FROM_BROWSER=safari` 等），可以**不放** `cookies.txt`。

## 运行

在 **`mac/app/`** 且已 `source .venv/bin/activate`：

```bash
python main.py           # 默认（由 .env 决定）
python main.py video     # 仅视频
python main.py cover     # 仅封面
python main.py both      # 视频 + 封面
python fill_drive_links.py
python push_export_to_feishu.py
```

或从任意目录：

```bash
bash /path/to/ins_to_drive/mac/run_main.sh
bash /path/to/ins_to_drive/mac/run_main.sh video
```

## 本目录结构

| 路径 | 说明 |
|------|------|
| `app/` | Mac 专用核心副本（`.py`、`requirements.txt`、`config.example.env` 等） |
| `app/README.md` | `app` 目录简要说明 |
| `setup_mac.sh` | 在 `mac/app/` 创建 `.venv` 并 `pip install` |
| `run_main.sh` | 在 `mac/app/.venv` 中执行 `python main.py` |
| `sync_secrets_to_app.sh` | 把根目录已有的密钥/`.env` 复制到 `mac/app/` |
| `运行教程.md` | 从准备环境到日常运行的完整教程 |

## 与 Windows 的对应

| Windows（仓库根目录） | Mac |
|----------------------|-----|
| `setup_windows.bat` | `mac/setup_mac.sh` |
| 根目录 `main.py` 等 | `mac/app/` 内同名文件 |
