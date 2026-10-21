FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SDR_DATA_DIR=/data \
    SDR_DEPLOYMENT_MODE=cloud \
    ASR_MODEL=/opt/asr-model \
    ASR_DEVICE=cpu \
    PORT=8765
COPY requirements.txt requirements-audio.txt ./
RUN pip install --no-cache-dir -r requirements-audio.txt
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='Systran/faster-whisper-small', local_dir='/opt/asr-model')"
COPY app app
COPY data data
COPY prompts prompts
COPY scripts scripts
COPY deploy/evaluation.public.json docs/evaluation.json
RUN useradd --create-home --uid 1000 appuser && mkdir -p /data && chown appuser:appuser /data
USER appuser
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8765')+'/healthz',timeout=3)"
CMD ["python","scripts/cloud.py"]
