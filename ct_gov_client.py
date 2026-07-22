"""ClinicalTrials.gov API v2 client. See api_source.md for the query/field-mapping spec."""

import time

import requests

BASE_URL = "https://clinicaltrials.gov/api/v2/studies"
USER_AGENT = "ADscape-pipeline/0.1 (+https://github.com/dhlee47/ADscape)"
REQUEST_DELAY_SECONDS = 0.2


def fetch_page(query_term=None, page_token=None, page_size=1000):
    params = {
        "query.cond": "Alzheimer Disease",
        "pageSize": page_size,
        "format": "json",
    }
    if query_term:
        params["query.term"] = query_term
    if page_token:
        params["pageToken"] = page_token

    response = requests.get(
        BASE_URL,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def iter_studies(query_term=None, page_size=1000):
    """Yields individual study dicts, paginating via nextPageToken until exhausted."""
    page_token = None
    while True:
        payload = fetch_page(query_term=query_term, page_token=page_token, page_size=page_size)
        for study in payload.get("studies", []):
            yield study
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
        time.sleep(REQUEST_DELAY_SECONDS)
