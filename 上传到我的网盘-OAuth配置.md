# 上传到「我的云端硬盘」：用 OAuth 登录（解决「无存储空间」报错）

若运行脚本时出现：

**"Service Accounts do not have storage quota"**

说明当前是用**服务账号**上传，服务账号没有自己的网盘空间，不能往你的「我的云端硬盘」里的文件夹上传。需要改成用**你自己的 Google 账号**登录上传（OAuth），文件会占用你的网盘空间。

---

## 一次性配置步骤（约 5 分钟）

### 1. 在 Google Cloud 创建 OAuth 客户端

1. 打开 **https://console.cloud.google.com/**，选中你之前建的那个项目（和 credentials.json 同一个项目）。
2. 左侧 **「API 和服务」** → **「凭据」**。
3. 点击 **「+ 创建凭据」** → **「OAuth 客户端 ID」**。
4. 若提示「要创建 OAuth 客户端 ID，请先配置同意屏幕」：
   - 点「配置同意屏幕」→ 选「外部」→ 填应用名称（如「Ins 上传」）、你的邮箱 → 保存并继续 → 作用域可跳过 → 保存并继续。
5. 回到「创建 OAuth 客户端 ID」：
   - 应用类型选 **「桌面应用」**。
   - 名称可填「Ins 上传桌面」。
   - 点「创建」。
6. 在弹窗里点 **「下载 JSON」**，浏览器会下载一个类似 `client_secret_xxxxx.json` 的文件。

### 2. 把密钥放到 ins_to_drive 文件夹

1. 把刚下载的 JSON 文件**复制**到 **ins_to_drive** 文件夹（和 main.py、credentials.json 同一层）。
2. 把该文件**重命名**为：**client_secret.json**（固定这个名字，脚本会读它）。

### 3. 再运行一次脚本

在终端里（已 cd 到 ins_to_drive、已激活 .venv）运行：

```bash
python3 main.py
```

第一次使用 OAuth 时，脚本会**自动打开浏览器**，让你用 **Google 账号登录**并授权。登录成功后，脚本会在 ins_to_drive 里生成 **token.json**，以后上传都会用你的网盘空间，不再弹出浏览器（除非 token 过期）。

---

## 说明

- **表格**仍然用服务账号读（credentials.json），无需改共享。
- **上传**改为用你的账号（client_secret.json + token.json），所以文件会出现在你的「我的云端硬盘」里你指定的文件夹，占用你的空间。
- 若删掉 **client_secret.json**，脚本会恢复为用服务账号上传（仅适合上传到「共享网盘」等，个人网盘会继续报无空间）。
