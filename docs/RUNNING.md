# 从 GitHub 获取并运行

本项目在评审自己的电脑运行，不需要云服务器、独立显卡、Docker或Node.js。推荐Python 3.12和现代浏览器；录音识别使用CPU，长录音需要等待。

## 1. 获取源码

在本项目GitHub仓库页面点击 **Code → Download ZIP**，解压后进入包含`README.md`、`app/`和`requirements-audio.txt`的目录。也可以使用Git克隆该仓库。

后续命令都在这个项目目录执行，不是在`app`或`scripts`子目录中执行。

## 2. Windows安装

在项目目录打开PowerShell：

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-audio.txt
Copy-Item .env.example .env
```

`Copy-Item`只在首次配置、尚无`.env`时执行。已配置过的`.env`应保留，不要覆盖。

## 3. 配置模型

用文本编辑器打开项目根目录的`.env`，填写自己的模型服务信息。例如使用本作业验证过的兼容接口：

```dotenv
LLM_BASE_URL=https://api.openai-proxy.org
LLM_MODEL=deepseek-v4.1-flash
LLM_API_KEY=填写自己的实际密钥
ASR_MODEL=small
ASR_DEVICE=cpu
```

如果使用其他OpenAI兼容服务，同时修改`LLM_BASE_URL`、`LLM_MODEL`和`LLM_API_KEY`。模型可用性、权限及额度由实际服务账号决定；仓库不包含开发者的私有密钥。

本机运行时`SDR_ACCESS_TOKEN`可保持为空。模型密钥由后端读取，网页无需输入模型密钥。修改配置后需重启程序。

## 4. 准备语音识别并启动

```powershell
.\.venv\Scripts\python.exe scripts/transcribe.py --prepare
.\.venv\Scripts\python.exe scripts/server.py run
```

第一次准备语音识别需要联网下载small模型，成功后保存在本地；以后可以复用，不需要每次下载。模型下载失败时不要跳过错误直接测试录音。

在浏览器打开 **http://127.0.0.1:8765**。完成上述安装后，Windows也可以双击`run.bat`启动。

只验证文本分析时，可以暂不准备语音模型；文本功能不依赖语音模型。录音功能需要安装音频依赖并完成模型准备。

## 5. 建议体验顺序

1. 通话分析页载入“题目示例·木里木外”，选择模型分析，点击开始分析。
2. 查看15字段、原文依据和五维意向评分。未知信息留空，企业主体歧义会提示人工核验。
3. 进入人工审核，修改字段，填写审核人和说明，保存并通过；查看审核记录。
4. 再分析其他示例，勾选多条线索，体验批量审核或统一订正。
5. 在真实录音页上传自己的MP3/WAV/M4A文件。等待全文转写，回听并核对角色/文本，再分析。
6. 导出已通过线索的CSV，或下载单条标准JSON。

原始题目录音、客户数据库和已有转写不随仓库公开；没有附带录音也可以独立运行。题目与合成示例已包含在程序中。

不配置模型密钥时，可显式选择“本地规则·对照基线”体验页面、审核和导出；这不是模型识别效果的替代证明。模型失败会明确提示，不会偷偷改用基线。

## 6. 停止

启动窗口按 **Enter**，或双击`停止项目.bat`。也可在同一项目目录执行：

```powershell
.\.venv\Scripts\python.exe scripts/server.py stop
```

程序等待当前任务完成后关闭，已保存线索和审核记录保留在`runtime/`。

## Linux / macOS

首次安装：

```bash
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-audio.txt
cp .env.example .env
```

编辑`.env`后执行：

```bash
.venv/bin/python scripts/transcribe.py --prepare
.venv/bin/python scripts/server.py run
```

浏览器地址相同；停止时在另一个终端、同一目录执行`.venv/bin/python scripts/server.py stop`。Windows归档已完成全新环境验证；其他操作系统仍需按实际平台检查音频依赖安装结果。

## 常见问题

| 情况 | 处理 |
| --- | --- |
| 找不到Python或版本不合适 | 安装Python 3.12并确保终端能识别，再创建虚拟环境 |
| `ModuleNotFoundError` | 使用同一个`.venv`解释器安装依赖和启动，不混用系统Python |
| 语音模型下载失败 | 检查网络后重新执行`--prepare`；已有faster-whisper模型目录时可将`ASR_MODEL`设为该目录，不使用普通Whisper的`.pt`文件代替 |
| 未配置模型、鉴权/额度错误 | 检查`.env`的三个模型配置项、账号权限和额度，然后重启；不要将密钥发到GitHub Issues |
| 本机8765端口已占用 | 改用`scripts/server.py run --port 8766`，访问`http://127.0.0.1:8766`；停止时也带`--port 8766` |
| 录音识别慢 | CPU按整段处理，等待进度；必要时调整`ASR_CPU_THREADS`。不要反复上传同一个文件 |
| 转写文字与听到的不一致 | 回听并修正后再分析；机器转写不保证逐字准确，未区分角色会触发人工审核 |

## 验证与设计说明

不调用模型API的程序测试：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

当前通过的测试与模型案例见[验收说明](ACCEPTANCE.md)，架构、Prompt和评分设计见[设计文档](DESIGN.md)。真实业务识别准确率的局限见[严格核对报告](STRICT_AUDIT.md)。
