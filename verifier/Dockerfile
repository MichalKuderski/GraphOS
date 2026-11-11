ARG PLAYWRIGHT_VERSION=1.64.1
FROM mcr.microsoft.com/playwright/python:v${PLAYWRIGHT_VERSION}-noble@sha256:330d401ae23c905896a0c26c66c36fc971b621519e7b11b435a8328d7bf6e031
ARG PLAYWRIGHT_VERSION=1.64.1
RUN --mount=type=secret,id=proxy_ca,required=false \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    python -m pip install --no-cache-dir playwright==${PLAYWRIGHT_VERSION} \
    && useradd --uid 10001 --create-home graphos-verifier \
    && mkdir -p /candidate /verifier \
    && chmod 755 /candidate /verifier
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --chmod=0555 . /verifier
USER 10001:10001
WORKDIR /tmp
CMD ["python", "-I", "/verifier/trusted_runner.py", "--profile", "static-web"]
