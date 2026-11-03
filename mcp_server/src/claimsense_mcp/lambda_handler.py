"""The MCP server and its registry on AWS Lambda.

The same app as `claimsense-mcp` (server.http_app), wrapped by Mangum, which turns a Lambda
Function URL event into an HTTP request for the app. The server is stateless, so each request
stands alone and any Lambda copy can answer it.

A fresh app is built for every request: Mangum runs the app's startup and shutdown around each
request, and the MCP SDK starts an app's request handling only once. Building the app is cheap.

Lambda handler setting: claimsense_mcp.lambda_handler.handler
Settings: CLAIMSENSE_API_URL (the Lambda Claims API) and CLAIMSENSE_MCP_PUBLIC_URL (this
function's own URL + /mcp, which the registry gives agents).
"""
from mangum import Mangum

from .server import http_app


def handler(event, context):
    # 0.0.0.0: requests arrive with the Function URL's host name, not localhost.
    return Mangum(http_app("0.0.0.0"), lifespan="auto")(event, context)
