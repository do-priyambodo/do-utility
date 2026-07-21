import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import subprocess
import json

try:
    from msal import ConfidentialClientApplication
except ImportError:
    ConfidentialClientApplication = None

try:
    from google.cloud import secretmanager
except ImportError:
    secretmanager = None

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
    if secretmanager:
        try:
            client = secretmanager.SecretManagerServiceClient()
            response = client.access_secret_version(request={"name": secret_name})
            return response.payload.data.decode("utf-8").strip()
        except Exception:
            pass
    # Fallback to gcloud CLI for local development/testing without pip library
    try:
        secret_part = secret_name.split("/")[-1]
        secret_id = secret_name.split("/")[-3] if "secrets/" in secret_name else secret_name
        return subprocess.check_output(["gcloud", "secrets", "versions", "access", secret_part, f"--secret={secret_id}"], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return subprocess.check_output(["gcloud", "secrets", "versions", "access", "latest", f"--secret={secret_name}"], text=True, stderr=subprocess.DEVNULL).strip()

# Get OAuth token for Graph API
def get_graph_token(tenant_id, client_id, client_secret):
    if ConfidentialClientApplication:
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
    else:
        # Fallback to requests for local development/testing without msal library
        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"
        }
        resp = http.post(token_url, data=payload, timeout=15)
        if resp.status_code == 200:
            return resp.json().get("access_token")
        else:
            raise Exception(f"Failed to get access token via REST: {resp.text}")

import time
import random

# Helper to handle OData paginated Microsoft Graph API requests with automatic 429 backoff & $top=999 maximization
def graph_get_paginated(url, headers, max_retries=5, timeout=30):
    results = []
    # Universal $top=25 pagination standard across Graph endpoints (/pages, /children, /sites, /drives, /lists)
    # Note: Microsoft Graph API does NOT support $top parameter on /subsites endpoint (returns HTTP 400 invalidRequest)
    if ("/pages" in url.lower() or "/children" in url.lower() or "/sites" in url.lower() or "/drives" in url.lower() or "/lists" in url.lower() or "/items" in url.lower()) and "/subsites" not in url.lower():
        if "?" in url and "$top=" not in url:
            url += "&$top=25"
        elif "?" not in url and "$top=" not in url:
            url += "?$top=25"
        if "/pages" in url.lower():
            timeout = max(timeout, 90)

    page_count = 0
    while url:
        page_count += 1
        for attempt in range(max_retries):
            try:
                response = http.get(url, headers=headers, timeout=timeout)
                if response.status_code == 200:
                    break
                elif response.status_code in [429, 502, 503, 504]:
                    retry_after = response.headers.get("Retry-After")
                    wait_time = int(retry_after) if (retry_after and retry_after.isdigit()) else min(30, (2 ** attempt) + random.uniform(0, 2))
                    print(f"⏳ Microsoft Graph API throttled/delayed (HTTP {response.status_code}). Backing off for {wait_time:.1f}s (Attempt {attempt+1}/{max_retries})...", flush=True)
                    time.sleep(wait_time)
                    continue
                elif response.status_code == 400:
                    raise ValueError(f"Graph API returned HTTP 400 (Non-retryable): {response.text}")
                else:
                    raise Exception(f"Graph API returned fatal status {response.status_code} for url {url}: {response.text}")
            except ValueError as e_val:
                raise e_val
            except Exception as e_net:
                if attempt + 1 >= max_retries:
                    raise e_net
                timeout = min(300, int(timeout * 1.5))
                wait_time = min(5, (2 ** attempt) + random.uniform(0, 1))
                print(f"⏳ Graph API network retry on {url[:60]}... ({e_net}). Retrying in {wait_time:.1f}s with adaptive timeout {timeout}s...", flush=True)
                time.sleep(wait_time)
        else:
            raise Exception(f"Graph API request failed after {max_retries} retry attempts: {url}")

        data = response.json()
        results.extend(data.get("value", []))
        if page_count > 1 and (page_count % 5 == 0 or page_count in [10, 25, 50, 100]):
            print(f"🔄 Phase 1 OData Paging Heartbeat: Fetched {page_count} pages ({len(results)} items so far in this folder/site query)...", flush=True)
        url = data.get("@odata.nextLink")
    return results
