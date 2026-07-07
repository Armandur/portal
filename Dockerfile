# Reservspår - primär drift är systemd user unit (se deploy/portal.service).
# Kräver --network host --pid host för att ss ska se värdens portar/PID:er.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends iproute2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" jinja2 markdown

COPY app ./app
COPY README.md ./

EXPOSE 8890

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8890"]
