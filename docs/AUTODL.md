# AutoDL 环境配置（本人测试）

## 先确认是否适合交付

AutoDL 可以运行 Python 后端和语音识别，但普通容器实例不支持嵌套运行 Docker，因此使用 Python 环境直接安装，不执行本项目的 Docker Compose 命令。

截至 2026-10-21，官方开放端口文档说明 6006/6008 可映射自定义服务，且开放端口需要企业认证；自定义服务补充协议还规定仅供本人科研使用，不向第三方转发链接。因此本指南只配置本人通过 SSH 隧道测试的环境，不把该地址作为已获准的面试 DEMO。若要给老师访问，先向 AutoDL 客服确认你的账号和用途是否允许；未确认时采用允许对外提供 Web 服务的托管位置。

官方说明：

- https://www.autodl.com/docs/env/
- https://www.autodl.com/docs/port/
- https://www.autodl.com/docs/service_agreement/

## 环境选择

已有实例可直接新建独立 Conda 环境，无需重装系统或更换镜像。建议 Python 3.12；CPU 转写先按至少 4 核、8 GB 内存、20 GB 可用磁盘准备，这是本项目的起步建议，实际耗时和峰值内存需要在实例上测量。

大语言模型通过 API 调用，不在 AutoDL 上部署 DeepSeek。默认语音识别为 faster-whisper small、CPU、int8；不要求 GPU，也不需要为了本项目专门购买高端 GPU。普通无卡模式官方配置为 0.5 核、2 GB，不建议用来验收完整录音转写性能。

资源与存储说明：

- https://www.autodl.com/docs/save_money/
- https://www.autodl.com/docs/instance_data/

## 上传与安装

在本机项目目录执行 `python scripts/package_deploy.py`，将生成的 `output/AI-SDR-Agent-deploy.zip` 通过 JupyterLab 上传到 `/root/autodl-tmp`。此包用于部署维护，不是邮件提交给老师的内容，也不包含本机密钥、客户数据库和原始录音。

在 AutoDL 的 JupyterLab 终端中执行：

```bash
cd /root/autodl-tmp
python -m zipfile -e AI-SDR-Agent-deploy.zip .
cd AI-SDR-Agent
conda create -n ai-sdr python=3.12 -y
conda activate ai-sdr
python -m pip install -r requirements-audio.txt
cp deploy/evaluation.public.json docs/evaluation.json
```

若实例已有同名环境，直接激活，不重复创建。安装需访问包源；出现错误时先保留错误信息，不能跳过安装失败继续验收。

## 私密配置

在 JupyterLab 文件编辑器中新建项目根目录下的 `.env`，填写以下配置。`LLM_API_KEY` 只填在服务器私密文件中，不要写进源码或聊天截图。

```dotenv
LLM_BASE_URL=https://api.openai-proxy.org
LLM_MODEL=deepseek-v4.1-flash
LLM_API_KEY=填写实际模型密钥
SDR_ACCESS_TOKEN=填写至少16个字符的随机演示访问码
SDR_DATA_DIR=/root/autodl-tmp/AI-SDR-Agent/runtime
ASR_MODEL=small
ASR_DEVICE=cpu
ASR_TIMEOUT=3600
```

访问码可在终端用 `python -c 'import secrets; print(secrets.token_urlsafe(24))'` 生成，私密保存后填入 `.env`。限制该文件权限：

```bash
chmod 600 .env
python scripts/transcribe.py --prepare
```

第一次准备语音模型需要下载模型文件，完成后再启动网页。后续识别使用本机已下载模型；不能把模型下载失败当作录音格式问题。若 Hugging Face 连接失败，可以在该准备命令的单独子 Shell 中使用 AutoDL 官方学术资源加速，避免加速设置持续影响模型 API 请求：

```bash
bash -lc 'source /etc/network_turbo && conda run -n ai-sdr python scripts/transcribe.py --prepare'
```

官方加速说明：https://www.autodl.com/docs/network_turbo/

数据库、上传文件和语音模型保存在配置的 runtime 目录中。不要释放实例或删除目录；重要数据另外备份。普通实例与 Pro 的数据保留规则不同，按实际实例类型查看控制台说明。

## 本人访问验证

在 AutoDL 终端保持以下进程运行：

```bash
conda activate ai-sdr
cd /root/autodl-tmp/AI-SDR-Agent
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765 --workers 1
```

在自己的 Windows PowerShell 中建立 SSH 隧道。将下面的 SSH 主机和端口替换成控制台给出的实际值；本地 8765 已被开发版占用时使用下面的 8766：

```text
ssh -N -L 8766:127.0.0.1:8765 -p 实际SSH端口 root@实际SSH主机
```

然后本人打开 `http://127.0.0.1:8766`，输入 `.env` 中设置的访问码。SSH 隧道和服务进程都要保持运行。这是本人访问方式，不能作为老师可直接打开的公网 DEMO。

先用不含客户隐私的测试材料验证：文本上传、MP3/WAV/M4A 上传、转写完整性、模型分析、审核保存、批量审核和导出。再验证服务重启后线索与审核记录仍存在。CPU 转写耗时需实测，不能仅凭首页能打开判断部署成功。

## 正式 DEMO 下一步

如果 AutoDL 明确允许此账号将该服务提供给面试老师，取得允许使用的 HTTPS 访问地址后，再设置 `SDR_PUBLIC_ORIGIN`、映射端口和云端入口，完成跨设备验证。没有这一步，不预设开放服务可用于此用途。

否则，将相同 Python 应用部署到允许外部访问的普通云服务器或 Web 托管平台；使用 `docs/DEPLOYMENT.md` 的 HTTPS 和持久化配置。无需重写应用，也无需自行部署大语言模型。
