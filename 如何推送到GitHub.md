# 把项目上传到 GitHub + 每次版本更新怎么做

你的仓库地址：**https://github.com/FloriaMingZHANG/ins-tiktok-youtube_to_drive**

---

## 一、第一次上传（本地项目 → 已有仓库）

你的 GitHub 上已经有这个仓库（目前只有 LICENSE）。下面是把本地 **ins_to_drive** 里的代码第一次推上去的完整步骤。

### 1. 打开终端，进入项目目录

**Mac：**
- 打开「终端」
- 输入（可直接把 `ins_to_drive` 文件夹拖进终端自动填路径）：
  ```bash
  cd /Users/floriazhang/Library/CloudStorage/OneDrive-bfsu.edu.cn/cursor/ins_to_drive
  ```
- 回车

### 2. 检查是否已经初始化过 Git

输入：
```bash
git status
```

- **若提示「not a git repository」**：说明还没初始化，从下面第 3 步开始做。
- **若出现「On branch main」或「On branch master」等**：说明已经是 Git 仓库，跳到下面「已初始化过的情况」小节。

### 3. 第一次：初始化并提交本地代码

在 **ins_to_drive** 目录下，**依次**执行（每行回车一次）：

```bash
# 初始化 Git
git init

# 添加所有文件（.gitignore 里的 .env、credentials 等不会加进去）
git add .

# 看下将要提交的文件（可选，确认没有 .env、credentials.json）
git status

# 第一次提交
git commit -m "Initial commit: full project - spreadsheet video to Drive"
```

### 4. 连上你的 GitHub 仓库并推送

```bash
# 添加远程仓库（你的真实地址）
git remote add origin https://github.com/FloriaMingZHANG/ins-tiktok-youtube_to_drive.git

# 主分支叫 main
git branch -M main

# 把 GitHub 上已有的 LICENSE 拉下来合并（仓库里已有内容时需要）
git pull origin main --allow-unrelated-histories --no-edit

# 推送到 GitHub
git push -u origin main
```

- 若提示输入 **用户名**：填你的 GitHub 用户名（如 FloriaMingZHANG）。
- 若提示输入 **密码**：填 **Personal Access Token**，不是登录密码。  
  Token 在这里创建：GitHub 网页 → 右上角头像 → **Settings** → 左侧 **Developer settings** → **Personal access tokens** → **Tokens (classic)** → **Generate new token**，勾选 **repo**，生成后复制粘贴到终端。

### 5. 验证

浏览器打开：https://github.com/FloriaMingZHANG/ins-tiktok-youtube_to_drive  
应能看到：README、main.py、requirements.txt、零基础操作指南等，且**没有** .env、credentials.json。

---

### 若你之前已经在本文件夹执行过 git init（已初始化过）

先看远程是否已经是你这个仓库：

```bash
cd /Users/floriazhang/Library/CloudStorage/OneDrive-bfsu.edu.cn/cursor/ins_to_drive
git remote -v
```

- **若没有 origin 或地址不对**：
  ```bash
  git remote add origin https://github.com/FloriaMingZHANG/ins-tiktok-youtube_to_drive.git
  ```
  若提示 origin 已存在，先删掉再加：
  ```bash
  git remote remove origin
  git remote add origin https://github.com/FloriaMingZHANG/ins-tiktok-youtube_to_drive.git
  ```

- **若已有 origin 且地址正确**，直接：
  ```bash
  git add .
  git commit -m "Initial commit: full project - spreadsheet video to Drive"
  git branch -M main
  git pull origin main --allow-unrelated-histories --no-edit
  git push -u origin main
  ```

---

## 二、每次版本更新时怎么做

以后每次改完代码、想更新到 GitHub，在 **ins_to_drive** 目录下做下面 3 步即可。

### 1. 打开终端并进入项目目录

```bash
cd /Users/floriazhang/Library/CloudStorage/OneDrive-bfsu.edu.cn/cursor/ins_to_drive
```

### 2. 查看改了哪些文件（可选）

```bash
git status
```

会列出修改/新增的文件。确认列表里**没有** .env、credentials.json、token.json 等。

### 3. 添加、提交、推送

```bash
# 把所有改动加入
git add .

# 提交，引号里写这次更新说明
git commit -m "这里写版本或更新说明"

# 推送到 GitHub
git push
```

**提交说明示例**（任选一种风格）：
- `v1.1: 支持 TikTok、YouTube、YouTube Shorts`
- `Fix: YouTube 403 使用 android 客户端`
- `Add: run.bat / run.sh，补充分发说明`
- `Docs: 更新零基础指南`

每次改完代码，就重复：**`git add .` → `git commit -m "说明"` → `git push`** 即可。

---

## 三、安全提醒：这些文件不会上传

`.gitignore` 已配置，以下内容**不会**被 `git add` 进去，也不会出现在 GitHub 上：

- `.env`
- `credentials.json`
- `client_secret.json`
- `token.json`
- `.venv/`、`venv/`

推送前用 `git status` 看一眼，列表里不应出现上述文件名；若出现，说明 .gitignore 被改过，需要改回再提交。
