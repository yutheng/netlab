#!/usr/bin/env python3
"""Week 7 lab, Step 4: add one ACL entry safely using an Idempotency-Key."""
import os
import sys
import time
import uuid

import requests

API = os.environ.get("LAB_API_URL", "http://api:8000")
TOKEN = os.environ["LAB_API_TOKEN"]  # export LAB_API_TOKEN=... first; never write it in this file

if len(sys.argv) != 2 or not sys.argv[1].isdigit() or len(sys.argv[1]) != 4:
    sys.exit("usage: python3 retry_safe.py <last 4 digits of your student ID>")
NN = int(sys.argv[1][2:])

ENTRY = {
    "action": "deny",
    "src": f"10.{NN}.30.0/24",
    "dst": f"10.{NN}.20.0/24",
    "protocol": "tcp",
    "port": 22,
    "description": "guests may not SSH to servers",
}

# 1. Generate ONE unique key BEFORE the retry loop starts
idem_key = f"step4-{uuid.uuid4()}"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Idempotency-Key": idem_key,
}

for attempt in range(1, 6):
    try:
        r = requests.post(f"{API}/api/v1/acl/entries", json=ENTRY, headers=HEADERS, timeout=5)
    except requests.ConnectionError as e:
        print(f"attempt {attempt}: no response ({type(e).__name__}) — trying again")
        time.sleep(1)
        continue
    if r.status_code in (429, 503):
        wait = int(r.headers.get("Retry-After", "1"))
        print(f"attempt {attempt}: {r.status_code} — waiting {wait}s")
        time.sleep(wait)
        continue
    print(f"attempt {attempt}: {r.status_code} {r.reason}: {r.json()}")
    # 2. Stop retrying once we get a final response
    break
