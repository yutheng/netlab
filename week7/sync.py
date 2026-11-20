#!/usr/bin/env python3
"""Week 7 Assignment (E2): Reconcile lab API VLANs and ACL entries with intent.yaml."""
import argparse
import hashlib
import json
import os
import random
import sys
import time
import uuid

import requests
import yaml

API = os.environ.get("LAB_API_URL", "http://api:8000").rstrip("/")


def normalize_acl(entry):
    """Return a canonical tuple for comparing desired and actual ACL entries."""
    return (
        entry["action"],
        entry["src"],
        entry["dst"],
        entry.get("protocol") or "any",
        entry.get("port"),
        entry.get("description") or "",
    )


def acl_payload(entry):
    """Build the JSON payload to POST for an ACL entry."""
    payload = {
        "action": entry["action"],
        "src": entry["src"],
        "dst": entry["dst"],
        "protocol": entry.get("protocol") or "any",
        "description": entry.get("description") or "",
    }
    if entry.get("port") is not None:
        payload["port"] = entry["port"]
    return payload


class SyncClient:
    """Resilient API client that handles auth expiry, rate limits, and transient chaos."""

    def __init__(self, base_url):
        self.base_url = base_url
        self.token = None
        self.run_id = str(uuid.uuid4())

    def login(self):
        try:
            user = os.environ["LAB_USERNAME"]
            password = os.environ["LAB_PASSWORD"]
        except KeyError:
            sys.exit("Error: set LAB_USERNAME and LAB_PASSWORD in the environment first.")

        for attempt in range(1, 7):
            try:
                r = requests.post(
                    f"{self.base_url}/api/v1/auth/token",
                    json={"username": user, "password": password},
                    timeout=5,
                )
            except (requests.ConnectionError, requests.Timeout) as e:
                if attempt == 6:
                    raise RuntimeError(f"Login failed after 6 tries: {e}") from e
                time.sleep((2 ** (attempt - 1)) + random.uniform(0, 0.5))
                continue

            if r.status_code in (429, 503):
                wait = float(r.headers.get("Retry-After", 2 ** (attempt - 1)))
                time.sleep(wait)
                continue

            r.raise_for_status()
            self.token = r.json()["token"]
            return

        raise RuntimeError("Login failed after 6 attempts.")

    def request(self, method, path, *, json_body=None, idempotency_key=None, allow_404=False):
        """Send an HTTP request safely, handling 401, 429, 503, and dropped connections."""
        if self.token is None:
            self.login()

        url = f"{self.base_url}{path}"
        transient_failures = 0

        while True:
            headers = {"Authorization": f"Bearer {self.token}"}
            if idempotency_key is not None:
                headers["Idempotency-Key"] = idempotency_key

            try:
                r = requests.request(method, url, json=json_body, headers=headers, timeout=5)
            except (requests.ConnectionError, requests.Timeout) as e:
                transient_failures += 1
                if transient_failures >= 10:
                    raise RuntimeError(f"{method} {path} failed after 10 tries: {e}") from e
                delay = min(4, 2 ** (transient_failures - 1)) + random.uniform(0, 0.5)
                print(f"  [retry] {method} {path}: no response ({type(e).__name__}), waiting {delay:.2f}s")
                time.sleep(delay)
                continue

            if r.status_code == 401:
                print("  [auth] 401 Unauthorized — refreshing token")
                self.login()
                continue

            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", "1"))
                print(f"  [rate] 429 Too Many Requests — waiting {wait}s")
                time.sleep(wait)
                continue

            if r.status_code == 503:
                transient_failures += 1
                if transient_failures >= 10:
                    r.raise_for_status()
                delay = min(4, 2 ** (transient_failures - 1)) + random.uniform(0, 0.5)
                print(f"  [retry] {method} {path}: 503 Service Unavailable, waiting {delay:.2f}s")
                time.sleep(delay)
                continue

            if allow_404 and r.status_code == 404:
                return r

            r.raise_for_status()
            return r

    def get_state(self):
        """Fetch current VLANs (as {id: name}) and ACL entries (as list of dicts)."""
        vlans_data = self.request("GET", "/api/v1/vlans").json()
        # Handle either a bare list or {"items": [...]} depending on endpoint envelope
        vlan_list = vlans_data["items"] if isinstance(vlans_data, dict) and "items" in vlans_data else vlans_data
        current_vlans = {int(v["id"]): v["name"] for v in vlan_list}

        acl_data = self.request("GET", "/api/v1/acl/entries").json()
        acl_list = acl_data["items"] if isinstance(acl_data, dict) and "items" in acl_data else acl_data
        return current_vlans, acl_list


def build_plan(desired_vlans, desired_acl, current_vlans, current_acl):
    """Compare desired state against current state and return a structured plan."""
    vlan_create = []
    vlan_update = []
    vlan_delete = []

    for vid, name in sorted(desired_vlans.items()):
        if vid not in current_vlans:
            vlan_create.append((vid, name))
        elif current_vlans[vid] != name:
            vlan_update.append((vid, current_vlans[vid], name))

    for vid, name in sorted(current_vlans.items()):
        if vid == 1:
            continue  # Default VLAN 1 is protected and must never be deleted
        if vid not in desired_vlans:
            vlan_delete.append((vid, name))

    # Match ACLs by normalized tuple (handling potential duplicate entries cleanly)
    desired_counts = {}
    for entry in desired_acl:
        key = normalize_acl(entry)
        desired_counts[key] = desired_counts.get(key, 0) + 1

    acl_delete = []
    matched_counts = {}
    for entry in current_acl:
        key = normalize_acl(entry)
        if matched_counts.get(key, 0) < desired_counts.get(key, 0):
            matched_counts[key] = matched_counts.get(key, 0) + 1
        else:
            acl_delete.append(entry)

    acl_create = []
    seen_counts = {}
    for entry in desired_acl:
        key = normalize_acl(entry)
        if seen_counts.get(key, 0) < matched_counts.get(key, 0):
            seen_counts[key] = seen_counts.get(key, 0) + 1
        else:
            acl_create.append(entry)

    return {
        "vlan_create": vlan_create,
        "vlan_update": vlan_update,
        "vlan_delete": vlan_delete,
        "acl_create": acl_create,
        "acl_delete": acl_delete,
    }


def is_plan_empty(plan):
    return not any(plan.values())


def print_plan(plan):
    if is_plan_empty(plan):
        print("Plan: no changes needed (API already matches intent).")
        return

    print("Plan:")
    for vid, name in plan["vlan_create"]:
        print(f"  + CREATE VLAN {vid} ({name})")
    for vid, old_name, new_name in plan["vlan_update"]:
        print(f"  ~ UPDATE VLAN {vid}: '{old_name}' -> '{new_name}'")
    for vid, name in plan["vlan_delete"]:
        print(f"  - DELETE VLAN {vid} ({name})")
    for entry in plan["acl_delete"]:
        print(f"  - DELETE ACL #{entry['id']}: {entry['action']} {entry['src']} -> {entry['dst']} ({entry.get('description', '')})")
    for entry in plan["acl_create"]:
        proto = entry.get("protocol") or "any"
        port_str = f":{entry['port']}" if entry.get("port") is not None else ""
        print(f"  + CREATE ACL: {entry['action']} {entry['src']} -> {entry['dst']} {proto}{port_str} ({entry.get('description', '')})")


def apply_plan(client, plan):
    for vid, name in plan["vlan_create"]:
        client.request("PUT", f"/api/v1/vlans/{vid}", json_body={"name": name})
    for vid, _old, new_name in plan["vlan_update"]:
        client.request("PUT", f"/api/v1/vlans/{vid}", json_body={"name": new_name})
    for vid, _name in plan["vlan_delete"]:
        # allow_404=True handles the case where a prior DELETE succeeded before a lost response
        client.request("DELETE", f"/api/v1/vlans/{vid}", allow_404=True)

    for entry in plan["acl_delete"]:
        client.request("DELETE", f"/api/v1/acl/entries/{entry['id']}", allow_404=True)

    for idx, entry in enumerate(plan["acl_create"]):
        payload = acl_payload(entry)
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
        idem_key = f"sync-{client.run_id}-{idx}-{digest}"
        client.request("POST", "/api/v1/acl/entries", json_body=payload, idempotency_key=idem_key)


def states_match(desired_vlans, desired_acl, current_vlans, current_acl):
    # Ignore VLAN 1 unless explicitly listed in intent.yaml
    filtered_current_vlans = {
        vid: name for vid, name in current_vlans.items()
        if vid != 1 or 1 in desired_vlans
    }
    if filtered_current_vlans != desired_vlans:
        return False

    desired_sorted = sorted(normalize_acl(e) for e in desired_acl)
    current_sorted = sorted(normalize_acl(e) for e in current_acl)
    return desired_sorted == current_sorted


def main():
    parser = argparse.ArgumentParser(description="Sync lab API state with intent.yaml")
    parser.add_argument("intent_file", help="Path to intent.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan without making changes")
    args = parser.parse_args()

    with open(args.intent_file, "r", encoding="utf-8") as f:
        intent = yaml.safe_load(f) or {}

    desired_vlans = {int(v["id"]): v["name"] for v in intent.get("vlans", [])}
    if 1 in desired_vlans:
        sys.exit("Error: do not put VLAN 1 in intent.yaml (VLAN 1 is the protected default VLAN).")
    desired_acl = intent.get("acl", [])

    client = SyncClient(API)
    current_vlans, current_acl = client.get_state()
    plan = build_plan(desired_vlans, desired_acl, current_vlans, current_acl)
    print_plan(plan)

    if args.dry_run:
        return

    if not is_plan_empty(plan):
        apply_plan(client, plan)

    # Re-read state and verify convergence
    final_vlans, final_acl = client.get_state()
    if states_match(desired_vlans, desired_acl, final_vlans, final_acl):
        print("Result: API state matches intent.yaml.")
    else:
        sys.exit("Result: MISMATCH — API state still does not match intent.yaml!")


if __name__ == "__main__":
    main()
