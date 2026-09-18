from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
from fastapi.openapi.utils import get_openapi

app = FastAPI()

# Define a model for the API documentation
class APIInfo(BaseModel):
    title: str
    version: str
    description: str
    termsOfService: str
    contact: str
    licenseInfo: str

# Function to generate the API documentation file
@app.get('/generate-docs', response_class=Response)
def generate_docs(docs: APIInfo = APIInfo(title='My API', version='1.0.0', description='This is a sample API.', termsOfService='https://example.com/terms', contact='info@example.com', licenseInfo='MIT License')):
    openapi_dict = get_openapi(title=docs.title, version=docs.version, description=docs.description, routes=app.routes)
    openapi_dict['info'] = docs.dict()
    return Response(content=openapi_dict, media_type='application/json')

# Function to generate the API documentation file without a specific APIInfo object
@app.get('/generate-docs', response_class=Response)
def generate_docs_without_info(docs: APIInfo = APIInfo()):
    openapi_dict = get_openapi(title=docs.title, version=docs.version, description=docs.description, routes=app.routes)
    openapi_dict['info'] = docs.dict()
    return Response(content=openapi_dict, media_type='application/json')
