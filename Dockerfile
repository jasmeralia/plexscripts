FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/bin:${PATH}"

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY bin ./bin
COPY plexadm ./plexadm
COPY scripts ./scripts
COPY reference ./reference

RUN chmod +x /app/bin/plexadm /app/scripts/*.sh

CMD ["bash", "scripts/mass_process.sh"]
