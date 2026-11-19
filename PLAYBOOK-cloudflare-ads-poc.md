# Playbook: Cloudflare Logpush → DigitalOcean Agent Data Services

**Product / PoC:** Cloudflare HTTP request logs (AWS S3) ingested into DigitalOcean Agent Data Services (ADS)  
**Workspace:** `ads-cloudflare-poc` (region `tor1`)  
**Audience:** FDEs, ADS design partners, and anyone repeating this pattern for a new log or object-storage source  
**Voice:** This document describes what the team did and recommends how others can repeat it.

---

## 1. Purpose

This playbook records an end-to-end path from a private AWS S3 Logpush bucket to a queryable Iceberg table in ADS. It is written so another product team can reuse the same sequence: discover the source, lock schema and DDL, package a data flow from the official SDK example, deploy with the CLI, validate rows, and extract operational value with SQL.

The PoC proved that:

- ADS can read gzip-compressed NDJSON from a private AWS S3 bucket.
- A 33-column Cloudflare “hot path” subset is enough for useful reliability and performance queries.
- A working data flow can be deployed from `pipeline-py-s3-gzip` without migrating objects into Spaces first.

---

## 2. Outcome at a glance

| Item | Value |
|------|--------|
| Source bucket | `do-cf-logs` (AWS S3, `us-west-2`) |
| Source prefix used for ingest | `logs/20261110/` |
| Object format | `.log.gz` → gzip → NDJSON (one JSON object per line) |
| ADS workspace | `ads-cloudflare-poc` (`tor1`), UUID `0f4b52d4-4f9e-40e0-9d4c-3135fceffc5a` |
| Data flow | `cf-http-logs-poc`, UUID `717ca3a1-13e8-408d-aadd-f8df7f0bda3d` |
| Sink table | Iceberg `cf_request_log` |
| Template | `ads-dataflow-sdk` → `examples/pipeline-py-s3-gzip` |
| Access model | Read-only AWS IAM user + workspace Spaces secret `my-input-s3` |

Ingest was stopped after a partial backfill (on the order of ~100 objects / tens of millions of rows), which was sufficient for PoC queries. Full-day completion was not required.

---

## 3. Architecture (what runs)

```text
AWS S3 (do-cf-logs)
  logs/YYYYMMDD/*.log.gz
        │
        │  s3poll (prefix + lookback)
        ▼
ADS data flow (cf-http-logs-poc)
  runtime gunzip → CsvObjectSource (1 line = 1 field)
        │
        ▼
Python entry (s3_gzip)
  parse JSON → cast → hash ClientIP → IcebergSink
        │
        ▼
Iceberg table: cf_request_log
  (+ cf_request_log_failed for bad lines)
        │
        ▼
ADS Catalog / Semantic Query (SQL)
```

Important runtime behaviours from the SDK example:

- Gzip is handled by the runtime (magic bytes), not by project code.
- NDJSON is read as a one-column CSV with a delimiter that never appears in JSON.
- One data flow writes **one** Iceberg table. Extra tables need extra flows.
- Redeploying against the same table **appends**; it does not replace. For a clean run, use a new table name.

---

## 4. Prerequisites

Before starting a similar PoC, the team should have:

1. An **ADS workspace** (active) and its **UUID** and **region slug** (for example `tor1`).
2. A DigitalOcean **personal access token** with custom scopes for **`ads_dataflow`** and **`ads_query`**.
3. Access to the source object store (here: AWS S3) with at least **list + get** on the target prefix.
4. Local tools: Python 3.11+, `make`, Go (for building `ads-data-flow`), `jq`, AWS CLI v2, and `gh` auth to `github.internal.digitalocean.com` if using internal repos.
5. The example project:  
   `https://github.internal.digitalocean.com/digitalocean/ads-dataflow-sdk/examples/pipeline-py-s3-gzip`  
   Follow **that** folder’s README (not only the repo root README).

---

## 5. Phase A — Discover the S3 source

### 5.1 Confirm credentials and listing

The team authenticated with AWS and listed the bucket structure:

```bash
aws sts get-caller-identity
aws s3 ls s3://do-cf-logs/ --region us-west-2
aws s3 ls s3://do-cf-logs/logs/ --region us-west-2
aws s3 ls s3://do-cf-logs/logs/20261110/ --region us-west-2 | wc -l
```

Observed layout:

```text
s3://do-cf-logs/
  logs/
    20261108/
    20261109/
    20261110/    ← ~2,715 .log.gz objects in this PoC
    20261111/
    ...
```

Each object was typically ~80–95 MB compressed. Uncompressed size for a sample object was on the order of ~1.5 GB.

### 5.2 Sample one object locally

The team downloaded one object and inspected lines:

```bash
aws s3 cp \
  s3://do-cf-logs/logs/20261110/<object>.log.gz \
  ./sample.log.gz --region us-west-2
gunzip -k ./sample.log.gz
head -n 1 ./sample.log | jq .
```

**Decision for future products:** always pull one real object before designing DDL. Do not invent columns from documentation alone.

---

## 6. Phase B — Understand the schema

### 6.1 Record shape

Each decompressed line was a single JSON object: a Cloudflare **HTTP request** Logpush event. Across the sample, the team measured **102 fields** per record. The natural grain was:

- **One row = one edge request**
- **Primary event id = `RayID`**
- Parent linkage via `ParentRayID` (`00` for root requests)

Traffic in the sample included DigitalOcean product hosts (for example OTLP collectors, API, webhooks), which matters when interpreting “sessions” (these are request events, not browser logins).

### 6.2 Field groups (mental model)

| Group | Example fields | Use |
|-------|----------------|-----|
| Identity | `RayID`, `ParentRayID`, `ZoneName`, timestamps | Lookup / lineage |
| Request | host, method, path, URI, protocol, bytes, UA | Traffic shape |
| Outcome | `EdgeResponseStatus`, `OriginResponseStatus`, bytes, content type | Reliability |
| Performance | TTFB, origin duration, RTT | Latency |
| Cache | `CacheCacheStatus`, cache statuses | Cache behaviour |
| Client context | country, ASN, device, SSL | Geo / network |
| Security (full schema) | WAF / bot / firewall fields | Threat analysis (phase 2) |

### 6.3 Privacy notes

- `ClientIP` is PII. The SDK example **hashes** it before write (pseudonym, not full anonymization).
- `OriginIP` / `EdgeServerIP` may also be sensitive depending on policy.
- Cookies and header maps can hold secrets; they were excluded from the PoC hot table.

---

## 7. Phase C — Create and align DDL

The team produced three DDL artefacts and then narrowed to a PoC subset.

### 7.1 Postgres designs (analytics modelling)

1. **Single wide table** (`cloudflare_http_requests.sql`) — one table, all 102 fields, Postgres types (`inet`, arrays, `jsonb`).
2. **Multi-table design** (`cloudflare_logs_postgres.sql`, Mansi) — three 1:1 fact tables on `ray_id` plus a colo reference:
   - `cf_request_log` (~33 columns) — hot path (~90% of queries)
   - `cf_request_security` — WAF / bot / firewall
   - `cf_request_detail` — deep debugging fields
   - `ref_edge_colo` — colo lookup (seeded manually, not by a data flow)

**Validation:** both Postgres DDLs covered all 102 source fields. Types matched the sample (including floating `EdgeResponseCompressionRatio`).

### 7.2 Iceberg DDL for ADS

ADS engineering converted / aligned the model to the SDK Iceberg dialect (`cloudflare_logs_iceberg.sql`):

- Types used: `VARCHAR`, `BIGINT`, `BOOLEAN`, `DOUBLE`, `TIMESTAMPTZ`
- `inet` → `VARCHAR`
- `jsonb` / arrays → `VARCHAR` (JSON text) where needed
- No primary keys or indexes in `sink.ddl`
- Fact tables partitioned by `day(edge_start_timestamp)`
- Unqualified `CREATE TABLE IF NOT EXISTS <name>` matching `table = "..."` in the entry

### 7.3 PoC subset decision

**Decision:** for the first data flow, use only **`cf_request_log`** (33 business columns). Defer security and detail tables to later flows.

The shipped example `sink.ddl` also adds provenance columns written by the entry:

- `object_key`
- `line_no`
- `ingested_at`

Those three are required for debugging which S3 object and line produced a row.

---

## 8. Phase D — Choose the data-flow template

ADS engineering pointed the team at:

`ads-dataflow-sdk/examples/pipeline-py-s3-gzip`

That example already:

- Polls a private AWS S3 prefix
- Reads gzip NDJSON Cloudflare-shaped logs
- Maps a 33-column subset aligned with `cf_request_log`
- Writes via `IcebergSink`
- Sends bad lines to `<table>_failed`

**Decision:** copy that example into a working project directory and configure it, rather than inventing a new pipeline from scratch.

Working project used in this PoC:

```text
ads-cloudflare-poc/cf-http-logs-flow/
```

Configuration was applied with:

```bash
python3.11 scripts/configure.py \
  --table cf_request_log \
  name=cf-http-logs-poc \
  input.bucket=do-cf-logs \
  input.s3_endpoint="https://s3.us-west-2.amazonaws.com" \
  input.s3_region=us-west-2 \
  input.prefix=logs/20261110/
```

Unit tests in the example project were run locally (`unittest`) after configuration.

---

## 9. Phase E — Install the `ads-data-flow` CLI

Until a released binary exists, the CLI is built from the internal `cthulhu` branch documented in the example README (for example `nmykins/AIDC-1846-cli`).

### 9.1 Blocker: SSH clone failed

Cloning with `git@github.internal.digitalocean.com:...` failed with `Permission denied (publickey)` even though the engineer could browse the repo in the browser.

**Cause:** the local SSH public key was not registered on internal GitHub. Browser / `gh` HTTPS auth is separate from SSH.

**Resolution:**

1. Authenticate with `gh` against `github.internal.digitalocean.com`.
2. Run `gh auth setup-git -h github.internal.digitalocean.com`.
3. Clone over HTTPS:

```bash
GH_HOST=github.internal.digitalocean.com gh repo clone digitalocean/cthulhu ~/cthulhu-ads-cli -- \
  --branch nmykins/AIDC-1846-cli --single-branch --depth 1
```

4. Install:

```bash
make -C ~/cthulhu-ads-cli/docode/src/do/teams/aidata-cloud-platform/ads-data-flow install
export PATH="$PATH:$(go env GOPATH)/bin"
ads-data-flow --version
```

Optional hardening: add the local SSH public key under internal GitHub → Settings → SSH keys so future SSH clones work.

### 9.2 CLI vs README drift

The example README and the installed CLI differed slightly:

| README said | This CLI build used |
|-------------|---------------------|
| `ads-data-flow manifest verify` | `ads-data-flow manifest validate` |
| `ads-data-flow deploy --wait` | `ads-data-flow deploy` (no `--wait`) |

**Practice for future products:** run `ads-data-flow <command> -h` and trust the installed binary’s flags.

---

## 10. Phase F — Secrets and deploy

### 10.1 Workspace secret

In the ADS Control Panel for the workspace:

1. Open **Settings**.
2. Create a **Spaces secret** (not a custom secret).
3. Name it exactly **`my-input-s3`**.
4. Paste the AWS access key id and secret.

The form is labelled for Spaces, but the example uses it for AWS keys. The manifest references:

```toml
[input.secrets]
s3_access_key_id = "$['my-input-s3'].access_key_id"
s3_secret_access_key = "$['my-input-s3'].secret_access_key"
```

Any other secret name fails deploy with a missing secret reference.

### 10.2 Environment

```bash
cd ~/ads-cloudflare-poc/cf-http-logs-flow
export PATH="$PATH:$(go env GOPATH)/bin"
export DIGITALOCEAN_ADS_WORKSPACE="<workspace-uuid>"
export DIGITALOCEAN_ADS_REGION="tor1"
export DIGITALOCEAN_TOKEN="<pat-with-ads_dataflow-and-ads_query>"
```

### 10.3 Deploy sequence used

```bash
ads-data-flow manifest validate data-flow.toml
ads-data-flow list          # empty table is OK before first deploy
ads-data-flow deploy
ads-data-flow get <uuid>    # wait until STATE=active
```

Observed lifecycle:

1. `provisioning` — package attach / capacity coming up (not yet ingesting).
2. `active` — `s3poll` running; objects under the prefix begin to process.

---

## 11. Phase G — Read-only access and prefix strategy

### 11.1 Constraint

The AWS identity provided for the PoC was **read-only** (list + get). It could not create a new prefix or copy a 20-object subset inside `do-cf-logs`.

### 11.2 Options considered

| Option | Feasible with read-only? | Notes |
|--------|---------------------------|-------|
| Prefix `logs-poc/` + copy 20 keys | No | Needs `PutObject` |
| Prefix `logs/20261110/` full day | Yes | ~2,715 objects; large backfill |
| Download 20 locally → upload to team-owned Spaces | Yes | Exact small subset; extra bucket |
| Lexicographic sub-prefix | Partial | Not guaranteed to equal “head 20” |

### 11.3 Decision taken

The team pointed the data flow at **`logs/20261110/`** and accepted a large historical backfill for the first proof. After roughly **~100 objects** (tens of millions of rows) had landed, ingest was stopped deliberately so the PoC could move to validation and querying.

**Recommendation for future products with read-only source buckets:** stage a small subset into a destination the team controls (for example DigitalOcean Spaces), or obtain a dedicated small prefix from the source owner before the first deploy.

---

## 12. Phase H — Know when ingest is progressing or done

Row count alone is a weak progress signal. Prefer object coverage:

```sql
SELECT count(*) AS rows,
       count(DISTINCT object_key) AS objects_done
FROM tabular.ads_cloudflare_poc.cf_request_log;
```

```sql
SELECT round(100.0 * count(DISTINCT object_key) / 2715, 1) AS pct_of_day_prefix
FROM tabular.ads_cloudflare_poc.cf_request_log;
```

Treat a historical backfill as complete when, for 10–15+ minutes:

1. `count(DISTINCT object_key)` stops rising (near the expected object total).
2. `count(*)` stabilizes.
3. `max(ingested_at)` stops advancing.
4. The data flow remains `active` with an empty `LAST_ERROR`.

Note: `s3poll` continues watching for **new** objects after backfill. “Done” means the intended historical set finished, not that the process exited.

---

## 13. Phase I — Pause or stop mid-ingest

This CLI build did not expose a dedicated `pause` flag. To stop midway:

```bash
ads-data-flow delete <data-flow-uuid>
# or: ads-data-flow delete <uuid> -f
```

Effects:

- Further S3 processing stops.
- Iceberg table rows already written **remain**.
- Redeploying the same table name later can **append duplicates** if the same objects are read again. For a clean second run, configure a new table name (for example `cf_request_log_v2`).

Optional soft attempt (if supported by the control plane):

```bash
ads-data-flow update <uuid> --replicas 0
```

Prefer `delete` when a hard stop is required.

---

## 14. Phase J — Make the data useful

With a populated `cf_request_log`, the PoC value is operational SQL (and later agents on the same catalog), not more ingest.

### 14.1 Query path

In the workspace **Semantic Query** tab, use the fully qualified name:

```text
tabular.<schema>.<table>
```

`<schema>` is the workspace name with hyphens replaced by underscores  
(example: workspace `ads-cloudflare-poc` → schema `ads_cloudflare_poc`).

### 14.2 Starter queries

**Volume and coverage**

```sql
SELECT count(*) AS rows,
       count(DISTINCT object_key) AS objects,
       min(edge_start_timestamp) AS t_min,
       max(edge_start_timestamp) AS t_max
FROM tabular.ads_cloudflare_poc.cf_request_log;
```

**Top hosts**

```sql
SELECT client_request_host, count(*) AS requests
FROM tabular.ads_cloudflare_poc.cf_request_log
GROUP BY 1
ORDER BY requests DESC
LIMIT 20;
```

**5xx rate by host**

```sql
SELECT client_request_host,
       count(*) AS requests,
       sum(CASE WHEN edge_response_status >= 500 THEN 1 ELSE 0 END) AS s5xx,
       round(100.0 * sum(CASE WHEN edge_response_status >= 500 THEN 1 ELSE 0 END)
             / count(*), 2) AS pct_5xx
FROM tabular.ads_cloudflare_poc.cf_request_log
GROUP BY 1
HAVING count(*) > 1000
ORDER BY pct_5xx DESC
LIMIT 20;
```

**Latency by host**

```sql
SELECT client_request_host,
       round(avg(edge_time_to_first_byte_ms), 1) AS avg_ttfb_ms,
       round(avg(origin_response_duration_ms), 1) AS avg_origin_ms,
       count(*) AS requests
FROM tabular.ads_cloudflare_poc.cf_request_log
GROUP BY 1
ORDER BY avg_ttfb_ms DESC
LIMIT 20;
```

**Status and cache mix**

```sql
SELECT edge_response_status, count(*) AS n
FROM tabular.ads_cloudflare_poc.cf_request_log
GROUP BY 1 ORDER BY n DESC;

SELECT cache_cache_status, count(*) AS n
FROM tabular.ads_cloudflare_poc.cf_request_log
GROUP BY 1 ORDER BY n DESC;
```

**Failed lines**

```sql
SELECT failed_reason, count(*) AS n
FROM tabular.ads_cloudflare_poc.cf_request_log_failed
GROUP BY 1 ORDER BY n DESC;
```

### 14.3 PoC demo narrative for stakeholders

A useful demo walks through:

1. Source discovery (bucket / prefix / file type).
2. Schema → DDL → one hot table.
3. Deployed ADS data flow reaching `active`.
4. Three findings from SQL (top host, error rate, latency).
5. Explicit limits (read-only source, partial backfill, phase-2 tables deferred).

---

## 15. Checklist for the next product

Use this as a repeatable checklist when onboarding another S3 (or S3-compatible) log feed into ADS.

### Discover

- [ ] Confirm region, bucket, prefix, and retention/lookback implications  
- [ ] Confirm IAM: list + get at minimum; plan write/staging if a small subset is required  
- [ ] Download one object; document compression + serialization (for example gzip + NDJSON)  
- [ ] Count objects under the intended prefix before first deploy  

### Model

- [ ] Inventory fields from a real sample (do not guess)  
- [ ] Choose grain and primary business key  
- [ ] Mark PII / secrets; decide hash, drop, or restrict  
- [ ] Draft sink DDL in the SDK Iceberg dialect  
- [ ] Start with a **hot-path subset** (one table / one flow)  

### Build

- [ ] Start from the closest SDK example (`pipeline-py-s3-gzip` for gzip NDJSON on S3)  
- [ ] Copy to a working directory; run `scripts/configure.py`  
- [ ] Ensure `table = "..."` matches `sink.ddl`  
- [ ] Run local unit tests  

### Platform

- [ ] Create workspace; note UUID and region  
- [ ] Create Spaces secret with the **exact** name the manifest expects  
- [ ] Install / verify `ads-data-flow` (`-h` for real flags)  
- [ ] `manifest validate` → `deploy` → poll until `active`  

### Validate

- [ ] Catalog shows table + `_failed`  
- [ ] Object and row counts move as expected  
- [ ] Spot-check hashing / null IP handling  
- [ ] Run 3–5 business queries and capture findings  

### Operate

- [ ] Know how to stop (`delete`) without losing landed rows  
- [ ] Use a new table name for clean re-runs  
- [ ] Add secondary tables as **separate** data flows when needed  

---

## 16. Artefacts produced in this PoC

| Artefact | Role |
|----------|------|
| `poc-subset-20261110.txt` | Planned 20-object key list (not staged due to read-only) |
| `cloudflare_http_requests.sql` | Postgres single-table DDL (full schema) |
| `cloudflare_logs_postgres.sql` | Postgres multi-table DDL (Mansi) |
| `cloudflare_logs_iceberg.sql` | Iceberg DDL aligned to SDK dialect |
| `cf-http-logs-flow/` | Configured working copy of `pipeline-py-s3-gzip` |
| `cf-http-logs-flow/scripts/download-poc-subset.sh` | Download 20 keys locally (read-only friendly) |
| `cf-http-logs-flow/scripts/copy-poc-subset.sh` | Copy 20 keys in-bucket (needs write) |
| This playbook | Reusable process document |

---

## 17. Lessons learned

1. **Follow the example README for the specific pipeline**, then verify flags on the installed CLI.  
2. **Internal GitHub UI access ≠ SSH git access**; prefer `gh` HTTPS when SSH keys are not registered.  
3. **One sink table per data flow** in the current SDK model.  
4. **Read-only source credentials force a prefix strategy** before deploy; otherwise backfill volume can explode.  
5. **Partial ingest is enough for a PoC** if queries already answer reliability and performance questions.  
6. **Stopping mid-flight is normal**; delete the flow, keep the table, document object coverage.  
7. **Value is in Semantic Query findings**, not in finishing every historical object.

---

## 18. References

- ADS concepts: [How Agent Data Services Works](https://docs.digitalocean.com/products/agent-data-services/concepts/how-agent-data-services-works/)  
- SDK example (internal): `digitalocean/ads-dataflow-sdk` → `examples/pipeline-py-s3-gzip`  
- CLI source (internal): `digitalocean/cthulhu` branch used for `ads-data-flow` install (see example README)  
- Workspace used in this PoC: `ads-cloudflare-poc` (`tor1`)

---

*Document status: describes the Cloudflare × ADS PoC as executed through first active ingest, partial backfill, and query validation. Update table names, UUIDs, and prefixes when adapting to a new product.*
