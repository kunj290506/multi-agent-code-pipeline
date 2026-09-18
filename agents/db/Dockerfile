FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8012

# Query-generator API (default)
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8012"]

# Executor API (second service — run as a separate container or override CMD):
# CMD ["uvicorn", "executor_api:app", "--host", "0.0.0.0", "--port", "8013"]
