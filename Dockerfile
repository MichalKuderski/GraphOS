# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
WORKDIR /app
COPY requirements.lock pyproject.toml ./
RUN --mount=type=secret,id=proxy_ca,required=false \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir -r requirements.lock
COPY graphos ./graphos
COPY profiles ./profiles
COPY verifier ./verifier
RUN --mount=type=secret,id=proxy_ca,required=false \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-deps . && chmod -R a+rX /app \
    && useradd --uid 10001 --create-home graphos \
    && mkdir -p /data && chown 10001:10001 /data
USER 10001:10001
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GRAPHOS_ALLOW_REMOTE=1 GRAPHOS_RUNTIME_ROOT=/app
EXPOSE 8000
CMD ["python", "-m", "graphos", "serve", "--host", "0.0.0.0"]
