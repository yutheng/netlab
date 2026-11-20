# Week 7 — Talking to a Network API (Lab & Intent Reconciliation)

- **Student ID (last 4 digits):** `5015` (`NN = 15`)
- **Address blocks:** `10.15.0.0/16` (IPv4), `fd00:5015::/32` (IPv6)

---

## Lab Wrap-Up Answers

### 1. What does `docker network inspect apilab` show, and how is it built from Week 6's building blocks?
`docker network inspect apilab` displays a user-defined Linux bridge network (`"Driver": "bridge"`) with an IPv4 subnet (e.g., `172.18.0.0/16`), a gateway (`172.18.0.1`), and a `"Containers"` section listing both `api` and `client` with their assigned IP and MAC addresses.

Docker constructs this from Week 6's Linux networking primitives:
- **Network namespaces:** Each container (`api` and `client`) runs in its own isolated network namespace with a separate network stack, interfaces, and routing table.
- **Linux bridge:** Docker creates a virtual bridge interface (`br-<network-id>`) in the host kernel that acts as a virtual Layer 2 switch.
- **veth pairs:** For each container, Docker creates a virtual Ethernet (`veth`) pair—placing one end inside the container namespace as `eth0` and plugging the other end into the host Linux bridge so packets travel between `client` and `api`.
- **Embedded DNS:** Docker runs an internal DNS server (`127.0.0.11`) on the bridge network so `client` can resolve the container name `api` to its IP address.

---

### 2. For each status code in Step 2, what should a client do next — and which of them should it never retry?
- **`404 Not Found` (GET `/api/v1/vlans/77`):** The resource does not exist. Report it as missing (or treat it as already gone if deleting), and fix the target ID/URL if unexpected.
- **`405 Method Not Allowed` (POST `/api/v1/vlans/10`):** That HTTP method is unsupported on that endpoint. Fix the client code to use an allowed method (`GET`, `PUT`, `PATCH`, or `DELETE`).
- **`400 Bad Request` (POST malformed JSON):** The server could not parse the syntax. Fix the request payload formatting before sending again.
- **`422 Unprocessable Entity` (PUT VLAN `5000`):** Valid JSON syntax, but invalid field values (VLAN ID out of range `1–4094`). Fix the input values against the API schema.
- **`409 Conflict` (POST VLAN `10` which already exists):** Creating it conflicts with existing state. Read the existing resource (`GET`) or update it idempotently (`PUT`) instead of `POST`ing again.
- **`403 Forbidden` (PUT VLAN `30` with `viewer` token):** Valid token, but the role lacks write permission. Stop and re-authenticate with an authorized role (`netops`).
- **`429 Too Many Requests` (burst of 10 GETs):** Temporary rate limit exceeded. Read the `Retry-After` header, sleep for that duration, and **retry** the request.

**Which ones a client should never retry:** **`400`, `403`, `404`, `405`, `409`, and `422`**. These are deterministic client-side errors—repeating the exact same request without changing the payload, URL, method, or credentials will always produce the same failure. Only **`429`** is transient and safe to retry after waiting.

---

### 3. Why did `retry_naive.py` create duplicates, and how exactly does your fix prevent them? Why must the `Idempotency-Key` be chosen once, before the first attempt?
- **Why `retry_naive.py` created duplicates:** When `lose_responses: 0.5` caused the API to save the ACL rule and drop the connection before replying, `requests.post()` raised a `ConnectionError`. Because the client never received a reply, it assumed the creation had not happened and retried the `POST` without an `Idempotency-Key`—causing the server to treat each retry as a brand-new creation request. Additionally, `retry_naive.py` lacked a `break` statement after a `201 Created` response, so it kept looping through all 5 attempts even when requests succeeded.
- **How `retry_safe.py` prevents them:** `retry_safe.py` generates a single unique `Idempotency-Key` (`f"step4-{uuid.uuid4()}"`) **outside the retry loop** and attaches it to every attempt, plus adds `break` once a `201` response is received. When a retry reaches the server with the same `Idempotency-Key` and body, the server recognizes it and replays the cached `201 Created` response (`Idempotent-Replayed: true`) instead of inserting a duplicate entry.
- **Why the key must be chosen once before the first attempt:** If a fresh `Idempotency-Key` were generated on each retry attempt inside the loop, a retry after a dropped connection would arrive with an unseen key—defeating deduplication and still creating duplicate ACL entries.

---

### 4. How many requests did `inventory.py` send to read your devices, and why more than the number of pages?
With student ID `5015` (`NN = 15`), there are **215 devices** total (`200 + 15`). At `limit=10` devices per page, reading the entire inventory requires **22 pages** (21 pages of 10 devices and 1 final page of 5 devices).

- **In Step 5 (`errors_503: 0.2`):** `inventory.py` sent **29 requests** (22 successful page reads + 7 retries after `503 Service Unavailable` errors).
- **In Step 6 (`--token-ttl 5 --rate 2`):** `inventory.py` sent **34 requests** (22 successful page reads + 10 retries after `429 Too Many Requests` rate limits + 2 retries after `401 Unauthorized` token expirations).

The request count is higher than the number of pages because `self.requests` increments on every HTTP attempt sent—so whenever a page request fails due to a `503`, `429`, or expired `401` token and gets retried, that page takes two or more requests to succeed.

---

### 5. What did you find in the OpenAPI document that you'd never have guessed?
1. **ACL entries can only be created (`POST`), read (`GET`), and deleted (`DELETE`)—there is no `PUT` or `PATCH`:** Unlike `/api/v1/vlans/{id}`, `/api/v1/acl/entries/{id}` does not allow in-place updates, meaning modifying an ACL rule requires deleting the old entry and `POST`ing a new one.
2. **Reusing an `Idempotency-Key` with a different body returns `422`:** Instead of silently ignoring the new payload or overwriting the old entry, the API checks that the body matches the original request for that key and rejects mismatches with `422 Unprocessable Entity`.
3. **`/api/v1/devices` supports filtering by `site` and up to `limit=50`:** You can query a single site directly (`?site=kl-hq`, `pj-dc`, `penang`, or `johor`) instead of downloading every page and filtering client-side, and request up to 50 devices per page instead of the default 20.
4. **Strict schema constraints on VLAN names and ACL ports:** VLAN names must match `^[A-Za-z0-9_-]{1,32}$`, and specifying a `port` on an ACL entry when `protocol` is `any` or `icmp` is rejected (`port` is allowed on `tcp` or `udp` only).

---

## Assignment Answers (E4)

### 1. How does `sync.py` decide what to change?
`sync.py` loads `intent.yaml` and queries `GET /api/v1/vlans` and `GET /api/v1/acl/entries` to read the live state, then computes the diff inside `build_plan()`:
- **VLAN created:** If a VLAN ID in `intent.yaml` is missing from the live API dictionary, it is added to `vlan_create`. In `evidence/apply.txt`, **VLAN 30 (`lecturer`)** was not on the fresh API, so `sync.py` planned `+ CREATE VLAN 30 (lecturer)` via `PUT /api/v1/vlans/30`.
- **VLAN renamed or deleted:** If a VLAN ID exists on both sides with a different name, it is added to `vlan_update`. On the fresh API, VLAN 10 was named `'users'` while `intent.yaml` specified `'student'`, producing `~ UPDATE VLAN 10: 'users' -> 'student'` via `PUT /api/v1/vlans/10`. Any live VLAN absent from `intent.yaml` (except the protected default **VLAN 1**) is added to `vlan_delete` and removed with `DELETE /api/v1/vlans/{id}`.
- **ACL entry:** Because ACL IDs are server-assigned, `normalize_acl()` converts each rule into a canonical tuple `(action, src, dst, protocol, port, description)` (normalizing missing `protocol` to `"any"` and `description` to `""`). Live entries not matched in `intent.yaml` are queued in `acl_delete` (`DELETE /api/v1/acl/entries/{id}`), and unmatched desired entries are queued in `acl_create` (`POST /api/v1/acl/entries`). In `evidence/apply.txt`, `(permit, 10.15.99.0/24, 10.15.0.0/16, tcp, 22, management-ssh-all)` was missing on the fresh API, so it was queued as `+ CREATE ACL: permit 10.15.99.0/24 -> 10.15.0.0/16 tcp:22 (management-ssh-all)`.

---

### 2. For each kind of request your script sends, why is it safe to retry — or why doesn't your script retry it?
- **`GET` (`/api/v1/vlans`, `/api/v1/acl/entries`):** Safe to retry because `GET` is read-only and never modifies server state.
- **`PUT` (`/api/v1/vlans/{id}`):** Safe to retry because `PUT` is idempotent—writing `{"name": "lecturer"}` to `/api/v1/vlans/30` multiple times produces the exact same state as writing it once.
- **`DELETE` (`/api/v1/vlans/{id}`, `/api/v1/acl/entries/{id}`):** Safe to retry because `DELETE` is idempotent. If the first `DELETE` succeeded before a dropped connection (`lose_responses`), the retry gets `404 Not Found` (accepted via `allow_404=True`), leaving the resource deleted either way.
- **`POST` (`/api/v1/acl/entries` with `Idempotency-Key`) and `POST` (`/api/v1/auth/token`):** A bare `POST` without an `Idempotency-Key` is **not** safe to retry because it appends a duplicate entry if the first request succeeded before a dropped reply. `sync.py` makes ACL creation safe to retry by attaching a unique `Idempotency-Key` per rule so the server replays the original `201` response instead of creating duplicates. (`POST /api/v1/auth/token` only issues short-lived session tokens without altering configuration state.)
- **Never retried (`400`, `403`, `404` on reads, `422`):** Permanent client errors are immediately raised via `r.raise_for_status()` because retrying invalid payloads or unauthorized requests will never succeed without changing the request or credentials.

---

### 3. VLANs have `PUT`; ACL entries only have `POST`. How did that change your design, and how do you choose each `Idempotency-Key`?
- **Impact on design:** Because VLANs support `PUT /api/v1/vlans/{id}` with client-chosen IDs, `sync.py` can create or rename VLANs in place with a single idempotent request. Because ACL entries only support `POST` (with server-assigned IDs) and `DELETE`, `sync.py` cannot update an existing ACL rule in place—it must match rules by full content (`normalize_acl()`), `DELETE` outdated rules by `{id}`, and `POST` new ones with an `Idempotency-Key`.
- **How `Idempotency-Key` is chosen:** At startup, `SyncClient` creates a per-run UUID (`self.run_id = str(uuid.uuid4())`). For each planned ACL creation, `apply_plan()` hashes the canonical JSON payload (`digest`) and builds `sync-{client.run_id}-{idx}-{digest}` **once before the retry loop**, so every retry of that rule within the same run uses the identical key.
- **New key for every attempt:** If a response is dropped after the server saves the ACL rule, retrying with a new key makes the server treat it as a separate request, creating duplicate rules.
- **Same static key for every run:** If a rule is later deleted from the API and `sync.py` is run again to restore it, reusing an old key from a previous run causes the server to replay the cached `201` response (`Idempotent-Replayed: true`) without actually recreating the rule (or fail with `422` if a different rule later occupies that index).

---

### 4. What happens if two people run `sync.py` with different intents at the same moment? What would the API need to make that safe?
- **What happens during concurrent runs:** Both scripts fetch the same initial snapshot via `GET` and compute plans unaware of each other. As their writes interleave:
  1. **Last-writer-wins on shared VLAN IDs:** If both intents define the same VLAN ID with different names, whichever `PUT` arrives last overwrites the other.
  2. **Merged/corrupted hybrid state:** Non-overlapping VLANs and ACL entries from *both* intents get created, leaving the API holding a combination of both files rather than either person's desired configuration.
  3. **Race errors / verification mismatch:** One client may `DELETE` an entry the other just created, or both runs will fail at the final `states_match()` check because the resulting server state does not match their own `intent.yaml`.
- **What the API would need to make it safe:**
  - **Optimistic Concurrency Control (`ETag` / `If-Match`):** The API could return a state version `ETag` on `GET` responses and require `If-Match: <etag>` on mutations. If another client modifies the configuration first, the version changes and stale writes are rejected with `412 Precondition Failed`, prompting the client to re-read and re-plan.
  - **Atomic Bulk Endpoint or Server-Side Locking:** Alternatively, the API could provide a single transactional endpoint (e.g., `PUT /api/v1/config`) to replace the entire desired state atomically, or a lock endpoint so only one client can modify the configuration at a time.

---

### 5. Where are your credentials, and how did you make sure no token or password is in your repository?
- **Where credentials live:** `LAB_USERNAME` and `LAB_PASSWORD` are stored only in the `client` container's shell environment and read at runtime via `os.environ` inside `SyncClient.login()`. The bearer token is kept strictly in memory (`self.token`) and never written to disk.
- **Preventing leaks into files and evidence:** No passwords, usernames, or `lab_...` tokens are hardcoded in `sync.py`, `inventory.py`, `retry_safe.py`, or `intent.yaml`. Evidence files in `lab7/` and `evidence/` capture script stdout and `curl -s` response bodies without logging `Authorization` headers or token login responses.
- **Pre-commit verification:** Before committing and pushing to GitHub, I inspected `git status` and `git diff` and ran `git grep -E "netops-pass|viewer-pass|lab_"` across the repository to confirm zero secrets or full student IDs exist in any tracked file.

---

## AI Use

- **Tools used:** Gemini (conversational AI assistant).
- **How it was used:** Used to clarify Docker bridge networking and HTTP error semantics (`400` vs. `422`, `PUT` vs. `POST` idempotency), troubleshoot Python indentation and retry backoff limits under combined chaos in `inventory.py` and `sync.py`, structure the `intent.yaml` ACL rules on the `10.15.0.0/16` block, and refine the wording of the `README.md` explanations. All commands, scripts, and evidence files were executed, verified, and reviewed personally in the lab container environment.
