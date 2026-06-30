import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from msal import ConfidentialClientApplication
from google.cloud import secretmanager

# Global resilient HTTP session with automatic retry backoff for M365 throttling (429) & Gateway timeouts (504)
def get_resilient_session():
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

http = get_resilient_session()

# Helper to retrieve secret from Secret Manager
def get_secret(secret_name):
    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(request={"name": secret_name})
    return response.payload.data.decode("utf-8").strip()

# Get OAuth token for Graph API
def get_graph_token(tenant_id, client_id, client_secret):
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = ConfidentialClientApplication(
        client_id,
        client_credential=client_secret,
        authority=authority
    )
    scopes = ["https://graph.microsoft.com/.default"]
    result = app.acquire_token_for_client(scopes=scopes)
    if "access_token" in result:
        return result["access_token"]
    else:
        error_desc = result.get("error_description", "Unknown error")
        raise Exception(f"Failed to get access token: {error_desc}")

# Helper to handle OData paginated Microsoft Graph API requests
def graph_get_paginated(url, headers):
    results = []
    while url:
        response = http.get(url, headers=headers, timeout=60)
        if response.status_code != 200:
            raise Exception(f"Graph API returned status {response.status_code} for url {url}: {response.text}")
        data = response.json()
        results.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
    return results
