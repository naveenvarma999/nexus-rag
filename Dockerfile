FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/srv/backend
WORKDIR /srv
RUN python -c "import urllib.request; urllib.request.urlretrieve('https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem', '/srv/rds-ca.pem')"
COPY backend/requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home nexus
COPY --chown=nexus:nexus backend /srv/backend
COPY --chown=nexus:nexus frontend /srv/frontend
USER nexus
WORKDIR /srv/backend
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--no-access-log"]
