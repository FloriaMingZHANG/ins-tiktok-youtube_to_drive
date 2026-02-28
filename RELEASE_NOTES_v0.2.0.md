# v0.2.0 发布说明

## 新增与变更

- **DO_VIDEO / DO_COVER**：支持三种命令模式
  - `python main.py video` — 仅下载并上传视频
  - `python main.py cover` — 仅下载并导出封面
  - `python main.py both` — 视频和封面都处理（默认）

- **仅封面模式**：先尝试只拉取封面；若失败则先下载视频、提取封面后删除视频文件，保证封面能拿到。

- **FEISHU_EXPORT_DIR**：封面原图导出到 `feishu_export/covers/`，并生成 `feishu_export/links.csv`（命名、视频 Drive 链接、封面文件名），方便手动复制到飞书多维表格。

- **SKIP_DRIVE_COVER**：可不将封面图上传到 Google Drive，只导出到本地。

- **push_export_to_feishu.py**：可选脚本，从导出包（links.csv + covers）推送到飞书多维表格。

- **结束汇总**：运行结束后输出「成功 N 条」「失败 M 条」及每条失败原因。

- **.gitignore**：增加对 `feishu_export/` 的忽略。
