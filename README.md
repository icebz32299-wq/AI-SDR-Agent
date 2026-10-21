# AI SDR Agent

将销售电话沟通记录整理为题目要求的 15 字段 SQL（Sales Qualified Lead）线索，提供企业名称识别、意向评分、原文证据和人工审核工具。

技术栈：Python、FastAPI、SQLite、原生 HTML/CSS/JavaScript。无需前端构建、Node.js、Docker或独立显卡；录音转写默认使用 CPU。

## 获取源码与评审入口

- [公开 GitHub 仓库](https://github.com/icebz32299-wq/AI-SDR-Agent)
- [运行说明](docs/RUNNING.md)：安装、配置、语音模型准备、启动、停止及常见问题。
- [设计文档](docs/AI-SDR-Agent项目设计文档.pdf)：架构、工作流、Prompt、企业识别、意向评分和人工审核。

可在仓库页面选择 **Code → Download ZIP**，解压后进入包含本 README 的目录；也可通过 Git 下载：

```bash
git clone https://github.com/icebz32299-wq/AI-SDR-Agent.git
cd AI-SDR-Agent
```

已拿到源码文件夹时可直接从下面的环境安装开始。本项目采用题目允许的“GitHub 仓库 + 运行说明”交付方式，网页在评审本机启动后使用。

## 环境要求

- 推荐 Python 3.12，支持 Python 3.11 及以上版本。
- 现代浏览器。
- 模型分析需要自行配置 OpenAI 兼容接口和 API 密钥。
- 首次安装依赖和准备语音模型需要联网；语音模型使用 faster-whisper small，默认 CPU / int8。

## Windows 快速运行

将整个源码文件夹解压或复制到本机，在包含本 README 的目录打开 PowerShell，依次执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-audio.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

用文本编辑器打开 `.env`，填写模型服务的三个配置项：

```dotenv
LLM_BASE_URL=https://api.openai-proxy.org
LLM_MODEL=deepseek-v4.1-flash
LLM_API_KEY=填写自己的密钥
```

使用其他 OpenAI 兼容服务时，同时修改地址、模型名和密钥。已有 `.env` 时应保留配置。源码只附空密钥配置模板。

准备语音模型并启动：

```powershell
.\.venv\Scripts\python.exe scripts/transcribe.py --prepare
.\.venv\Scripts\python.exe scripts/server.py run
```

服务就绪后自动打开默认浏览器；也可手动访问 **http://127.0.0.1:8765**。完成安装后，Windows 可双击 `run.bat` 启动。只体验文本功能时，可以跳过语音模型准备。

停止：在启动窗口按 **Enter**，或双击 **停止项目.bat**。程序会等待正在执行的任务结束。无需自动打开浏览器时使用 `python scripts/server.py run --no-browser`。

## Linux / macOS

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-audio.txt
cp .env.example .env
# 编辑 .env，填写自己的模型配置
.venv/bin/python scripts/transcribe.py --prepare
.venv/bin/python scripts/server.py run
```

在另一个终端、同一项目目录执行 `.venv/bin/python scripts/server.py stop` 可停止服务。详细配置、端口调整和故障排查见 [运行说明](docs/RUNNING.md)。

## 建议体验顺序

1. 通话分析：载入“题目示例·木里木外”，或粘贴通话文本、上传 TXT，点击开始分析。
2. 查看线索：核对 15 字段、客户原句、企业候选及五维意向评分。
3. 人工审核：修改企业名称或意向，填写审核人和说明，保存通过并查看变更记录。
4. 批量处理：勾选多条线索，分别保存各条草稿，或预览后提交统一订正。
5. 录音分析：上传 MP3、WAV、M4A，等待本地全文转写，回听校对并标注角色后分析。
6. 导出：下载单条 JSON，或导出已审核线索的 JSON / CSV。

未配置密钥时可以显式选择“本地规则·对照基线”体验界面和审核流程；模型调用失败不会自动切换基线。意向为 high / medium / low；未知事实留空，企业主体不明和其他质量问题进入人工审核。

## 项目结构

```text
AI-SDR-Agent/
├── app/                     后端 API、工作流、存储、录音处理和网页
│   └── static/              页面、样式、浏览器交互
├── data/                    题目与合成示例、品牌和企业参考资料
├── prompts/                 版本化抽取提示词
├── scripts/                 启停、转写、评估、打包和可选部署工具
├── tests/                   核心规则、接口、审核事务和启动测试
├── docs/                    最终设计文档、运行说明与验证资料
├── deploy/                  可选云部署配置
├── .env.example             空密钥配置模板
├── requirements*.txt        核心、音频、测试及可选媒体工具依赖
├── run.bat                  Windows 启动入口
└── 停止项目.bat             Windows 停止入口
```

首次运行后自动创建 `runtime/`，保存数据库、上传录音、转写和模型缓存。该目录和虚拟环境不属于提交源码。

## 文档导航

- [最终项目设计文档（PDF）](docs/AI-SDR-Agent项目设计文档.pdf)
- [最终设计正文（Markdown）](docs/DESIGN_SUBMISSION.md)
- [完整运行说明](docs/RUNNING.md)
- [SQL 字段规则](docs/FIELD_RULES.md)
- [验收与评估](docs/ACCEPTANCE.md)
- [企业参考资料来源](docs/SOURCES.md)
- [录音材料说明](docs/MATERIALS.md)
- [提交材料说明](docs/SUBMISSION.md)

`docs/DESIGN.md` 是工程设计补充；开发阶段的核对、修复与录屏准备资料也保留在 `docs/`，以便追溯。最终设计内容以本次 PDF 和 `DESIGN_SUBMISSION.md` 为准。

## 测试与模型案例

不调用真实模型接口的程序回归测试：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
```

以下命令会调用自己配置的模型接口，产生相应 API 费用，并更新模型案例报告：

```powershell
.\.venv\Scripts\python.exe scripts/evaluate.py --mode llm
.\.venv\Scripts\python.exe scripts/audit_core.py
```

`docs/test-results.xml` 保存程序回归结果；`docs/evaluation.json` 只保留题目和合成模型案例，`docs/core-evaluation.json` 保存合成语义案例。程序测试通过数与真实业务识别准确率分别理解。

## 交付与数据

公开仓库：[icebz32299-wq/AI-SDR-Agent](https://github.com/icebz32299-wq/AI-SDR-Agent)。题目允许使用“GitHub 仓库 + 运行说明”作为 DEMO 交付，不必另租服务器。

本文件夹是一份可独立安装的完整源码副本。密钥、原始客户录音、运行数据库、私有转写、日志和虚拟环境不随源码提供；评审可使用题目文本示例或上传自己的测试文件。模型密钥仅由后端读取。录音在本地处理，点击模型分析时当前文本发送到所配置的服务。
