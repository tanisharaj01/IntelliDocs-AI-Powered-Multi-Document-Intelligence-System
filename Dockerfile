FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (required by PyMuPDF and other tools)
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose ports for both FastAPI (8000) and Streamlit (8501)
EXPOSE 8000 8501
