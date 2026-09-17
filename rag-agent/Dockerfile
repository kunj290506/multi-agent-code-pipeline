FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# NOTE: sentence-transformers downloads the embedding model (all-MiniLM-L6-v2)
# from HuggingFace on first run. Ensure outbound internet access or pre-cache
# the model at build time by adding:
#   RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

EXPOSE 8011

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8011"]
