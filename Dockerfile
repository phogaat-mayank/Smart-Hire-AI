FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download BERT model into container cache for instant startup
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy application files
COPY . .

# Default exposed port
EXPOSE 7860

# Start app with dynamic shell port expansion (defaults to 7860 or $PORT if provided by Railway/Render)
CMD ["sh", "-c", "gunicorn main:app --bind 0.0.0.0:${PORT:-7860} --timeout 120 --workers 1"]
