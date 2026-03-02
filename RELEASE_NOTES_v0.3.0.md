# v0.3.0 发布说明 — Windows 支持

## 新增功能

### Windows 一键配置
- **setup_windows.bat**：Windows 用户双击即可完成虚拟环境创建与依赖安装，无需手动输入命令。
- **run.bat 增强**：自动检测 Mac 格式的 .venv，删除并重建为 Windows 格式；无虚拟环境时自动创建。

### 文档更新
- **README / 分发说明**：修正 Windows 虚拟环境激活命令（`activate.bat` / `Activate.ps1`），新增 Windows 快速开始说明。

### 稳定性修复
- **临时目录清理**：上传失败时，临时文件清理不再因文件占用而崩溃（`ignore_cleanup_errors=True`）。
- **Cookie 兼容**：文档说明 Edge/Chrome 运行时 cookie 被锁定的问题，推荐使用 Firefox 或 cookies 文件。

## 使用方式

| 平台 | 首次配置 | 日常运行 |
|------|----------|----------|
| **Windows** | 双击 `setup_windows.bat` | 双击 `run.bat` 或 CMD 中 `.venv\Scripts\activate.bat` + `python main.py video` |
| **Mac** | `python3 -m venv .venv` + `source .venv/bin/activate` + `pip install -r requirements.txt` | `./run.sh` 或 `python3 main.py video` |

## 兼容性

- 本版本同时支持 **Mac** 与 **Windows**，配置（.env、credentials.json）可跨平台共用。
- Mac 用户：使用 `run.sh`；Windows 用户：使用 `run.bat` 或 `setup_windows.bat`。
