# AI SDR Agent

从销售通话到有证据的结构化线索。Python + FastAPI + SQLite；原生 HTML/CSS/JavaScript，无前端构建步骤。

评审首次使用请看[从GitHub获取并运行](docs/RUNNING.md)，包含下载、密钥配置、CPU语音模型准备、启动/停止和常见问题。无需租用服务器。

## 获取源码

在[GitHub仓库](https://github.com/icebz32299-wq/AI-SDR-Agent)点击Code → Download ZIP并解压，或执行：

```bash
git clone https://github.com/icebz32299-wq/AI-SDR-Agent.git
cd AI-SDR-Agent
```

## 快速运行

推荐Python 3.12（支持3.11+）。在本目录执行，包含录音转写所需依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-audio.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# 在本地编辑 .env，填写模型密钥；已经有 .env 时不要覆盖。
.\.venv\Scripts\python.exe scripts/transcribe.py --prepare
.\.venv\Scripts\python.exe scripts/server.py run
```

打开 <http://127.0.0.1:8765>。已有 Python 依赖的本机也可以双击 `run.bat`。

首次准备语音模型需要联网下载，成功后再测试录音上传。文本模型分析使用评审自行配置的API密钥；不配置密钥时可以显式选择规则基线体验对照流程，但不能代替真实模型效果验证。

Linux/macOS使用 `python3 -m venv .venv`，后续将上述`.\.venv\Scripts\python.exe`换成`.venv/bin/python`，复制配置使用`cp .env.example .env`。可以在另一个终端执行`.venv/bin/python scripts/server.py stop`停止服务。

停止项目：在启动窗口按 **Enter**，或者双击项目目录的 **`停止项目.bat`**。会等待当前任务完成后关闭，不需要按 Ctrl+C。请使用 `run.bat` 或上面的启动命令，停止脚本才能识别本项目；旧版直接启动的Uvicorn窗口需先关闭一次。

模型密钥通过私有`.env`配置，不进入可分享源码。接收项目的人应自行配置密钥。代理平台实际返回的模型标识保存在每条线索的运行记录里，不将请求名等同于已验证的底层模型版本。

## 核心体验

1. 通话分析：保留“通话文本 / 真实录音”两个切换。文本页可粘贴、载入示例或上传TXT；录音页可选择材料或上传本地MP3/WAV/M4A。上传录音后自动本地转写，完成后点击“开始分析”；推荐逐行标注“销售：”“客户：”。
2. 查看线索概览、原文证据、企业候选、五维评分卡以及严格的15字段JSON。
3. 人工审核：修正企业和意向；调整意向须填写新依据，所有变更保留前后快照。
4. 批量订正：预览统一修改，任一版本冲突则整批回滚。
5. 已审核数据导出CSV；单条JSON可下载草稿，草稿带 `need_human_review=true`。
6. 效果验证页明确区分回归测试、模型案例验证和尚未完成的真实业务准确率评估。

本地规则基线无需密钥，是显式选择的对照模式。模型失败不会悄悄切换基线或创建一条假成功记录。

## 真实录音与本地转写

默认读取本项目的同级 `SDR真实通话录音` 文件夹，递归查找音频，排除 `__MACOSX`、`._*`。原始文件不复制、不更名；接口只返回脱敏编号和号码。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-audio.txt
.\.venv\Scripts\python.exe scripts/transcribe.py --prepare
# 页面上传录音会自动转写；选择题目录音时，点击“本地转写”。也可离线批处理：
.\.venv\Scripts\python.exe scripts/transcribe_materials.py --limit 3
# 不指定 --limit 时处理全部；已缓存录音自动跳过。
```

首次准备需要下载模型，之后从本地加载。机器转写不自动声称完成说话人分离；页面提供逐段角色标注及文本修正，未知角色会触发审核。缓存存于 `runtime/transcripts/`，音频不发送至模型接口；点击模型分析时，当前转写文本才会发送到配置的代理服务。

开发环境将可选音频依赖隔离在 `.tools/`；标准安装使用独立虚拟环境。音频库固定兼容版本，避免 PyAV 新接口变更。

## 配置

| 配置项 | 用途 |
| --- | --- |
| `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` | OpenAI格式代理接口、本地模型名和密钥 |
| `LLM_TIMEOUT` | 模型请求超时秒数，最大240 |
| `SDR_RECORDINGS_DIR` | 原始录音目录；空值使用同级材料目录 |
| `SDR_DATA_DIR` | 工作区数据库、转写及模型缓存目录 |
| `SDR_ACCESS_TOKEN` | 可选访问令牌；对外提供服务时设置 |
| `ASR_MODEL` / `ASR_DEVICE` | 本地转写模型名或已下载模型目录，默认small / cpu |
| `ASR_CPU_THREADS` | CPU转写线程数，默认4，可按实际CPU配额调整 |
| `ASR_TIMEOUT` | 单次本地转写超时秒数，默认3600，最大14400 |
| `TAVILY_API_KEY` | 可选企业网页候选检索，不等同工商核验 |

企业检索未配置时，系统会明确提示；品牌词库不是工商数据库。企业主体通过人工核验反馈形成有地区、行业约束的别名映射。所有企业归属无法唯一确定时，保留不确定性。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q --junitxml=docs/test-results.xml
# 下面两项会实际调用配置的模型接口：
.\.venv\Scripts\python.exe scripts/probe_api.py
.\.venv\Scripts\python.exe scripts/evaluate.py --mode llm
```

模型评估输入是题目示例与明确标识的合成案例；报告不冒充38段真实录音的独立准确率。真实材料评估需要人工核对转写、核验企业主体并按业务口径标注意向。见 [验收与评估](docs/ACCEPTANCE.md)。

新增语义挑战检查使用`tests/fixtures/core_cases.json`，执行`python scripts/audit_core.py`会实际调用配置的模型，结果写入`docs/core-evaluation.json`。这些是开发者编写的合成边界案例，不作为独立业务准确率。逐条PDF核对与尚未解决的问题见 [严格核对报告](docs/STRICT_AUDIT.md)。

## DEMO与邮件提交

题目允许DEMO二选一：**可访问的在线Demo，或GitHub仓库＋运行说明**。本项目选择GitHub仓库方案，无需租用服务器。评审获取仓库后按本页步骤配置并运行，`127.0.0.1:8765`是运行后的本机地址。邮件同时提供设计文档和与最终版本一致的录屏文件，详见 [提交清单](docs/SUBMISSION.md)。仓库地址：[https://github.com/icebz32299-wq/AI-SDR-Agent](https://github.com/icebz32299-wq/AI-SDR-Agent)。

若以后需要在线Demo，公网部署作为可选方案，见 [部署说明](docs/DEPLOYMENT.md)。

## 交付导航

- [题目要求与实现计划](docs/REQUIREMENTS.md)
- [设计文档：架构、Prompt、企业消歧、意向评分、审核闭环](docs/DESIGN.md)
- [字段规则](docs/FIELD_RULES.md)
- [验收与评估](docs/ACCEPTANCE.md)
- [本轮功能核对与优化](docs/PROJECT_AUDIT.md)
- [企业参考资料来源与归属边界](docs/SOURCES.md)
- [录音材料与本地使用说明](docs/MATERIALS.md)
- [录屏讲解脚本](docs/DEMO_SCRIPT.md)
- [提交清单与已知边界](docs/SUBMISSION.md)
- [机器可读模型验证报告](docs/evaluation.json)

运行数据、原始录音和密钥不应随源码公开。发布仓库前需单独检查文档、验证报告和截图是否含真实业务信息；不能直接上传整个工作区。`scripts/package.py`生成可分享源码归档，自动排除私有材料清单、真实业务截图和运行数据，并将评估报告替换为题目/合成案例版本；这不等于已经发布GitHub仓库。题目原始PDF与音频保留在项目外的原位置。

准备GitHub时，先执行`python scripts/package.py`，将生成的`output/AI-SDR-Agent-source.zip`解压到一个新目录并检查内容，再从该目录创建仓库，避免将开发工作区中的私有资料一起加入。

## 目录

```text
app/        API、抽取工作流、证据校验、企业消歧、录音索引、静态页面
data/       题目示例、合成案例、明确标为品牌的候选词库
prompts/    版本化抽取Prompt
scripts/    接口验证、评估、音频批处理、打包
tests/      核心逻辑与API事务测试
docs/       设计、验收、录屏与测试报告
runtime/    私有运行数据（忽略）
```

### 上传、转写与模型失败的处理

默认启动使用稳定运行模式，不开启代码热重载；修改Python代码后需重启服务。开发时可自行使用Uvicorn的`--reload`，但改代码会中断进行中的任务。

录音在本地完整解码后识别；过小音量会适度放大，反相立体声避免下混相消；大量重复、长录音有效语音过少或没有识别文本时，自动调整语音检测重试一次，并保留更可靠的结果。人声稀少的录音仍会提示回听，不能据文件时长补造通话内容。

模型解析支持有限重试：输出截断时增加输出额度，临时限流/服务错误或超时时重试，JSON结构异常时重新要求标准结构。只兼容未知值null、整数型字符串等不改变语义的格式差异，保留事实证据与15字段的校验，不会用本地规则冒充模型成功。模型失败后无需重新上传或转写，当前文本会保留。

本地`runtime/diagnostics.jsonl`记录阶段、错误码、次数与耗时，不记录密钥、通话正文或模型思考内容。转写的依赖、模型加载、解码、超时和模型服务的鉴权、限流、截断、格式错误可分别定位。
