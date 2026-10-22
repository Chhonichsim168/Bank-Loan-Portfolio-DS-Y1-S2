FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
# Run as an unprivileged user; /app/data is the only writable place (mount it as a volume).
RUN useradd -r -u 10001 creditdesk && mkdir -p /app/data && chown -R creditdesk /app/data
USER creditdesk
VOLUME ["/app/data"]
# Hosting services (Render, Railway, Fly...) tell the app which port to use in $PORT; 8501 otherwise.
ENV PORT=8501
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:%s/_stcore/health' % os.environ.get('PORT','8501')).status==200 else 1)"
CMD ["sh", "-c", "streamlit run app.py --server.address=0.0.0.0 --server.port=${PORT} --server.headless=true"]
