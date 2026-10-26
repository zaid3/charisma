FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY charisma ./charisma
RUN python -m pip install --no-cache-dir '.[server]' && python -m pip check \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin charisma \
    && mkdir -p /data && chown charisma:charisma /data
COPY deploy/gunicorn.conf.py /app/gunicorn.conf.py
USER 10001:10001
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/ready',timeout=3)"
CMD ["gunicorn", "--config", "/app/gunicorn.conf.py", "charisma.web:create_app()"]
