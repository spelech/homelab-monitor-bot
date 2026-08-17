# Stage 1: Build React + TypeScript Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Runtime Python Container
FROM python:3.12-slim
WORKDIR /app

# Install system dependencies & docker client tools if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application backend
COPY app/ ./app/
COPY cli.py triage_routing.py ./

# Copy built frontend assets from stage 1
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist/

# Set environment
ENV PYTHONPATH=/app
ENV HOST=0.0.0.0
ENV PORT=9013

EXPOSE 9013

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9013"]
