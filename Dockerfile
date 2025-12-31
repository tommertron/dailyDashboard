FROM python:3.12-slim

WORKDIR /app

# Install SSH client for the todos refresh feature
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Copy application files
COPY server.py generate_summary.py index.html ./

EXPOSE 8000

CMD ["python3", "server.py"]
