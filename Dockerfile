# syntax=docker/dockerfile:1
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
       > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# OpenShift CLI (oc)
RUN curl -fsSL https://mirror.openshift.com/pub/openshift-v4/clients/ocp/stable/openshift-client-linux.tar.gz \
    | tar -xz -C /usr/local/bin/ oc \
    && chmod +x /usr/local/bin/oc

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
    "fastapi>=0.111.0" \
    "uvicorn[standard]>=0.29.0" \
    "pyyaml>=6.0" \
    "python-dotenv>=1.0.0" \
    "python-multipart>=0.0.9" \
    "requests>=2.31.0"

COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
