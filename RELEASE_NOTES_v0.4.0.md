# v0.4.0 发布说明 — 小红书支持 + 画质优化

## 新增

### 一键运行（Windows）
- 新增 **`一键运行.bat`**：双击即可完成首次配置引导 + 日常运行，适合无编程基础的用户
  - 自动检测 Python 是否安装（未安装时显示下载链接）
  - 自动检测 `credentials.json`（缺失时显示配置步骤）
  - 自动检测 `.env`（缺失时复制模板并用记事本打开引导填写）
  - 自动创建虚拟环境并安装依赖

### 小红书支持
- 支持下载 **小红书** 视频，链接格式：`https://www.xiaohongshu.com/explore/xxx`
- 短链 `xhslink.com` 会跳转，若失败可手动展开后粘贴
- 需 yt-dlp >= 2024.5.0（已更新 requirements.txt）

### 画质优化
- 新增 `-f bestvideo+bestaudio/best`，优先下载**分离的音视频流并合并**，确保原画质或最高可用画质
- **Instagram / TikTok / YouTube / 小红书**：均按平台提供的最高画质下载
- YouTube 继续使用 android 客户端，可获取更高码率

## 画质说明

| 平台 | 画质策略 |
|------|----------|
| YouTube | bestvideo+bestaudio 合并，android 客户端 |
| Instagram | bestvideo+bestaudio/best |
| TikTok | bestvideo+bestaudio/best |
| 小红书 | bestvideo+bestaudio/best |

若平台仅提供单文件（音视频已合并），则自动 fallback 到 `best` 单文件最佳画质。
