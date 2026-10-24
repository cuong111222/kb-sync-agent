FROM python:3.11-slim

WORKDIR /app

# Prevent Python from writing .pyc files and buffer stdout
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Copy dependency definition
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and modules
COPY scraper/ /app/scraper/
COPY storage/ /app/storage/
COPY ai/ /app/ai/
COPY tests/ /app/tests/
COPY main.py /app/main.py

# Run main.py once and exit
CMD ["python", "main.py"]
