FROM python:3.11-slim as base

# Prevent Python from writing pyc files and keep stdout unbuffered
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user (Rule 3 Security) with GID 101 (telegram-bot-api) for shared volume read access
RUN groupadd -g 101 telegram-api && useradd -m -u 1000 -G telegram-api botuser

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=botuser:botuser . .

USER botuser

EXPOSE 443

CMD ["python", "bot.py"]
