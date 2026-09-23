import os, httpx
from dotenv import load_dotenv
load_dotenv()
key = os.getenv('GROQ_API_KEY')
res = httpx.get('https://api.groq.com/openai/v1/models', headers={'Authorization': f'Bearer {key}'})
print([m['id'] for m in res.json().get('data', [])])
