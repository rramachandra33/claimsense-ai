"""The data API on AWS Lambda.

The same FastAPI app, wrapped by Mangum, which turns a Lambda Function URL (or API Gateway) event
into an ordinary HTTP request for the app and the app's response back into what Lambda returns.
Nothing else changes: the token check, the access rule, the rate limit and the audit log all run
exactly as they do under uvicorn.

Lambda handler setting: claimsense_api.lambda_handler.handler
"""
from mangum import Mangum

from .main import app

# lifespan "off": the app has no startup or shutdown work, and Lambda may freeze it at any time.
handler = Mangum(app, lifespan="off")
