FROM python:3.12-slim

WORKDIR /app

# Install dependencies first
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the source code
COPY src/ ./src/

# Expose the port the app runs on
EXPOSE 8081

# Run uvicorn (no reload + bind to 0.0.0.0 instead of localhost)
CMD ["uvicorn", "src.kvs.main:app", "--host", "0.0.0.0", "--port", "8081"]