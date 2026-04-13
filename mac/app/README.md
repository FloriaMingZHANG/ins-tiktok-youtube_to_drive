# Mac 专用工作副本

这里是**从仓库根目录复制出来的核心文件**，供你在 Mac 上开发与运行；**请只在本目录（`mac/app/`）里改代码**，避免与 Windows 根目录下的同名文件混用、互相覆盖。

## 与根目录的关系

- 根目录仍保留 Windows 常用脚本（`.bat`）及原 `main.py` 等，方便 PC 使用。
- 若你希望 Mac 与 Windows **逻辑一致**，在根目录改过核心逻辑后，可手动把对应 `.py` 再复制进本目录（或按需合并）。

## 首次使用

1. **凭证放到本目录**：若仓库**根目录**已有 `credentials.json` / `.env` / `cookies.txt` 等，在仓库里执行一次  
   `bash mac/sync_secrets_to_app.sh`  
   即可复制到 **`mac/app/`**。详见上级 **`mac/README.md`**。
2. 若还没有 `.env`，在本目录执行：
   ```bash
   cp config.example.env .env
   ```
   再编辑 `.env`（与仓库根目录 README 说明相同）。
3. 回到仓库里执行一次（在任意目录均可）：
   ```bash
   bash mac/setup_mac.sh
   ```
4. 运行：
   ```bash
   cd "/path/to/ins_to_drive/mac/app"
   source .venv/bin/activate
   python main.py
   ```
   或使用 `bash mac/run_main.sh`（见上级 `mac/README.md`）。

## 本目录包含

`main.py`、`feishu.py`、`fill_drive_links.py`、`push_export_to_feishu.py`、`highlight_m4a_rows.py`、`list_m4a_to_sheet.py`、`requirements.txt`、`config.example.env`、`LICENSE`。

虚拟环境目录为 **`mac/app/.venv`**（仅 Mac，与根目录 `.venv` 无关）。
