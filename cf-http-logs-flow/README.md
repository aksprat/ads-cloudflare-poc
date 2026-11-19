# pipeline-py-s3-gzip

Gzip-compressed NDJSON objects in an AWS S3 bucket in, an Iceberg table out. The `s3poll` datapump watches a prefix of your bucket and
references each new object, the runtime decompresses it, `CsvObjectSource` cuts it into lines, the entry (`s3_gzip.pipeline:Entry`) parses each line as a
JSON object, and `IcebergSink` appends the rows to a table, named `request_log` as shipped (step 10 renames it). A line that cannot become a row lands in
`<table>_failed` with its reason.

The data is a web request log in the shape of a Cloudflare Logpush `http_requests` dataset: one request per line, keyed on `RayID`. The table is a
33-column subset of it (see `s3_gzip/sink.ddl`); fields on a line that the table does not name are ignored. It is a template for any gzip NDJSON feed:
change `FIELDS` in `s3_gzip/logs.py` and the same columns in `sink.ddl`. There are two sample files in `testdata/`, named for what they hold:

- `requests_clean.log.gz`: 6 good lines. Every line is accepted.
- `requests_with_errors.log.gz`: 9 lines, 4 good and 5 bad, each bad line for a different reason.

## How gzip and NDJSON are handled

There is no NDJSON source in the runtime, and gzip needs no code of yours:

- **Gzip is the runtime's job.** Before any object Source reads an object, the runtime decodes it (gzip, zstd, bzip2 or xz) into a second scratch
  file. The codec is picked by the object's leading magic bytes, never by its name, so `.log.gz`, a gzip named `.log` and a plain object all work.
  A corrupt or truncated object is one failed record for the whole object (`object.decompress.corrupt`, `object.decompress.eof`; a `.tar.gz` is
  `object.archive`), and none of its lines are accepted. Nothing in this project touches gzip. It needs a runtime with this stage (cthulhu #186502,
  2026-11-13 or later); on an older one a gzip object fails in `CsvObjectSource`.
- **NDJSON is read as a one-column CSV.** `CsvObjectSource` is configured with `has_header = "false"` and a delimiter, `\u0001`, that never occurs in
  JSON text, so each line is one field. `source.ddl` names that one column `line`. Quotes only mean something at the start of a CSV field and a JSON
  line starts with `{`, so the quotes inside a line stay as they are. The Source adds `source_ref` (the object key) and `source_offset`
  (the 0-based line number).
- **The entry parses.** It gets the table of lines, parses and casts each one against `FIELDS`, and returns the accepted table and the failed rows.
  `ObjectSource` could also feed an entry that returns one table of many rows per object (the entry returns the table, it does not `yield` per
  record), but then a bad line cannot be failed on its own: `failed_table` names records, and a record is the whole object. Cutting the object
  into lines in the Source keeps one `_failed` row per bad line, with its raw text and line number, and keeps each unit small.

A line over `max_record_bytes` (4 MiB here, raised from the 1 MiB default) fails in the Source as `csv.too_large.truncated`. A line that starts with `"`
is read as a quoted CSV field and may fail in the Source (`csv.parse`); an NDJSON object starts with `{`, so it never does.

## What the data flow does with the sample files

`requests_clean.log.gz` has six lines and all six are accepted. `requests_with_errors.log.gz` has nine lines. Four are good. Five fail, each for a
different reason, all by the entry:

| Line (0-based) | Problem | Reason |
|---|---|---|
| 4 | not JSON | `author.malformed_json` |
| 5 | JSON, but a list | `author.not_an_object` |
| 6 | `RayID` is empty | `author.missing_ray_id` |
| 7 | `RayID` repeats line 1 | `author.duplicate_in_object` |
| 8 | `EdgeResponseStatus` is `teapot` | `author.bad_value.edge_response_status` |

So uploading both files gives your table 10 rows (6 + 4) and `<table>_failed` 5. A blank line fails as `author.blank_line`, and a line with no usable
`EdgeStartTimestamp` as `author.bad_value.edge_start_timestamp`. A value that does not fit its column fails its line as `author.bad_value.<column>`: text
or a fraction in a whole-number column, or a whole number outside the 64-bit range. An array, an object or a boolean in a text column is not a failure: it
is stored as JSON text (`["a","b"]`, `true`). Uniqueness of `RayID` is checked within one unit (a slice of one object, at most
`max_records` lines), not across units or objects: the two sample files share `ray0001` to `ray0004`, so the table holds them twice. Dedupe at query
time (`ROW_NUMBER() OVER (PARTITION BY ray_id ...)`).

## Files

| File | Role |
|---|---|
| `data-flow.toml` | The v3 manifest the `ads-data-flow` CLI reads: your bucket as a user input store, `s3poll`, `CsvObjectSource` as a line reader, `IcebergSink`. |
| `manifest.src.json` | The same manifest in JSON, for the SDK's Makefile and tests. The CLI does not read it, and `configure.py` does not edit it. |
| `s3_gzip/source.ddl` | The one column the Source cuts each line into: `line VARCHAR`. |
| `s3_gzip/sink.ddl` | `CREATE TABLE IF NOT EXISTS <table>` (`request_log` as shipped), partitioned by `day(edge_start_timestamp)`. The runtime runs it only when the table is absent. |
| `s3_gzip/logs.py` | `FIELDS` (column, type, source field), per-line parsing and casting, and the unit table in, accepted table and failed rows out. Pure pyarrow. |
| `s3_gzip/pipeline.py` | The entry: `table = "request_log"` as shipped, called once per unit. |
| `testdata/requests_clean.log.gz` | A sample object with 6 good lines. |
| `testdata/requests_with_errors.log.gz` | A sample object with 4 good lines and 5 bad ones, described above. |
| `scripts/install-prereqs.sh` | Installs `make`, `go`, `jq`, the AWS CLI and a Python 3.11 or newer if they are missing. |
| `scripts/configure.py` | Sets keys in `data-flow.toml` and the table name in `pipeline.py` and `sink.ddl`, in one command. |
| `scripts/make_sample.py` | Regenerates `testdata/`. |
| `tests/` | Unit tests with a stand-in Source and no network, and for `configure.py`. |

The entry declares `table = "<table>"` (`request_log` as shipped), and `sink.ddl` must create that same name, unqualified: any other name, or a
qualified one, fails setup. The runtime puts the table in your workspace's schema. Both `.ddl` files sit inside the package so the packer carries them
beside the code.

The Source adds `source_ref` (the object key) and `source_offset` (the 0-based line number) to every row. The entry stores them as `object_key` and
`line_no`, and adds `ingested_at`. A `source.ddl` that names `source_ref` or `source_offset` is refused.

`ClientIP` is stored as a truncated SHA-256 (`logs.hash_ip`), not the address. That is a pseudonym, not anonymization: the same address always gives the
same hash, and an IPv4 address can be recovered by hashing every possible one. `OriginIP` is stored as it is; hash it the same way if your policy requires. Cookies and header objects are not in this table; if you add them to `FIELDS`, they are JSON text and may hold secrets.

## Before you start

This project is in the `examples/pipeline-py-s3-gzip` folder of the [ads-dataflow-sdk](https://github.internal.digitalocean.com/digitalocean/ads-dataflow-sdk) repository. If you have not cloned it yet:

```bash
git clone https://github.internal.digitalocean.com/digitalocean/ads-dataflow-sdk.git
cd ads-dataflow-sdk/examples/pipeline-py-s3-gzip
```

Run every command in this guide from that folder.

Tick each box before you begin. If one is missing, ask the ADS preview team.

- [ ] **An ADS workspace**, already created. Open **Agent Data Services** in the DigitalOcean dashboard and check that it is active.
- [ ] **Its UUID.** Copy it from the workspace page in the dashboard.
- [ ] **Its region slug,** for example `tor1` for Toronto. The CLI puts it in the address of every request.
- [ ] **An AWS account** in which you can create an S3 bucket and an IAM user.

## Set up S3 and upload the logs

**1. Create the bucket (AWS console).** In S3, create a bucket and leave **Block all public access** on. Any region works: the data flow reads it over
the internet, so it does not have to match the workspace's. Then save its name and region, for example `us-east-2`:

```bash
export BUCKET_NAME="<your bucket name>"
export AWS_REGION="<the bucket's region, for example us-east-2>"
```

**2. Upload the logs (AWS console).** Open your bucket, create a folder named exactly `logs`, open it, and upload both `testdata/requests_clean.log.gz`
and `testdata/requests_with_errors.log.gz` from this project. The folder name must be exactly `logs/`, because that is the prefix the data flow watches
(`input.prefix` in `data-flow.toml`). Only gzip NDJSON files go there: every other object under `logs/` is read as NDJSON too. A data flow reads only
objects modified in the last 7 days (`pump.options.lookback` is `168h`), so deploy within a week of uploading. The poll runs every 10 seconds, so the
data flow picks the files up soon after it starts.

**3. Check it landed (AWS console).** Open the `logs` folder in your bucket. You should see `requests_clean.log.gz` and `requests_with_errors.log.gz`. If
the folder is empty or missing, the upload went to the wrong place.

**4. Create an API token for the CLI (DigitalOcean dashboard).** The CLI sends this token with every request to create, update and
delete the data flow, so it needs the permissions for **data flows** and **query**. This is a personal access token (PAT) with custom scopes:

1. In the left panel, under **Account**, open **API**.
2. Click **Generate New Token**, give it a name, and choose an expiry.
3. Choose **Custom scopes**.
4. In **Search resource types**, type `ads`. Tick **`ads_dataflow`** and **`ads_query`**. Ticking a group's box selects all five of its permissions.
5. Click **Generate Token**.

```
DigitalOcean dashboard -> Account -> API -> Generate New Token -> name, expiry -> Custom scopes -> search "ads" -> tick ads_dataflow and ads_query -> Generate Token
```

Copy the token before you leave the page, because it is shown only once. Then save it. It stays in your shell and is never printed:

```bash
read -s "DIGITALOCEAN_TOKEN?DigitalOcean API token: "; export DIGITALOCEAN_TOKEN    # bash: read -s -p "DigitalOcean API token: " DIGITALOCEAN_TOKEN; export DIGITALOCEAN_TOKEN
```

## Set your variables

Run this from this project's folder, after you replace every placeholder. `BUCKET_NAME` and `AWS_REGION` (step 1) and `DIGITALOCEAN_TOKEN` (step 4) are
already set. Every later command reads all of these. If you open a new terminal, run this block again, and the exports from steps 1 and 4 (and `IAM_USER`, if you are past step 8).

```bash
export DIGITALOCEAN_ADS_WORKSPACE="<workspace UUID>"
export DIGITALOCEAN_ADS_REGION="<region slug, for example tor1>"
export DATA_FLOW_NAME="<your data flow name>"
export TABLE_NAME="<your table name>"
```

- `DIGITALOCEAN_ADS_WORKSPACE` and `DIGITALOCEAN_ADS_REGION` are your workspace's UUID and region slug. The CLI reads them,
  and puts the region in the address of every request.
- `DATA_FLOW_NAME` is lowercase letters, digits and hyphens, at most 32 characters. A data flow with the same name in the
  workspace is updated by `deploy`, not created: pick a name that is not in use.
- `TABLE_NAME` is the table your rows go to. Pick a name of your own: lowercase letters, digits and underscores, starting with
  a letter. The files ship with `request_log`; step 10 renames it. The data flow also creates `<TABLE_NAME>_failed` for the lines it
  cannot write.

Then check them. It prints a table, and the token shows only as `set` and its length:

```bash
red=$(printf '\033[31m'); end=$(printf '\033[0m')
printf '%-28s %s\n' VARIABLE VALUE
for v in DIGITALOCEAN_ADS_WORKSPACE DIGITALOCEAN_ADS_REGION BUCKET_NAME AWS_REGION DATA_FLOW_NAME TABLE_NAME; do
  eval "val=\${$v}"; if [ -n "$val" ]; then out="$val"; else out="${red}MISSING${end}"; fi; printf '%-28s %s\n' "$v" "$out"
done
if [ -n "$DIGITALOCEAN_TOKEN" ]; then out="set (${#DIGITALOCEAN_TOKEN} characters)"; else out="${red}MISSING${end}"; fi
printf '%-28s %s\n' DIGITALOCEAN_TOKEN "$out"
```

Anything shown in red is missing: set it and run the check again.

## Part A: Prepare your machine

**5. Install the tools.** Installs whatever is missing and skips the rest. Works on macOS (Homebrew), Debian/Ubuntu (apt) and Fedora (dnf); it asks for `sudo` on Linux. On Windows, install WSL with Ubuntu and run everything in the Ubuntu terminal.

```bash
bash scripts/install-prereqs.sh
```

| Tool | What it is for | Install by hand |
|---|---|---|
| `python3` 3.11 or newer | runs `configure.py` and the tests | `brew install python@3.13`, or `uv python install 3.13` |
| `make` | builds the CLI | `xcode-select --install` (Mac), or your package manager |
| `go` 1.27 or newer | builds the CLI (an older Go that supports toolchain switching downloads it by itself) | `brew install go`, or download it from go.dev/dl |
| `jq` | finds your data flow's UUID in step 19 | `brew install jq`, or your package manager |
| `aws` 2.32 or newer (AWS CLI v2) | signs in to AWS and creates the read-only key in step 8 | `brew install awscli`, or the [AWS installer](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) |

**6. Get the CLI.** `ads-data-flow` packs the project and creates or updates the data flow. Until it has a release, you build it from source, in a single-branch, shallow clone of cthulhu (the clone is large). It needs Go 1.27 or newer, `git` and `make`, which step 5 installed; Docker is not needed.

```bash
git clone --branch nmykins/AIDC-1846-cli --single-branch --depth 1 git@github.internal.digitalocean.com:digitalocean/cthulhu.git ~/cthulhu-ads-cli
make -C ~/cthulhu-ads-cli/docode/src/do/teams/aidata-cloud-platform/ads-data-flow install
```

Then check it. If you get `command not found`, add Go's bin directory to your `PATH` first: `export PATH="$PATH:$(go env GOPATH)/bin"`.

```bash
ads-data-flow --version
```

**7. Sign in to AWS, if you are not already.** Step 8 creates an IAM user, so the CLI needs to be signed in to an account that can do that. First check
whether it is. If this prints your account and the user or role you are signed in as, you are done: skip to step 8.

```bash
aws sts get-caller-identity
```

If it fails (for example `Unable to locate credentials`, or `The security token included in the request is expired`), sign in. `aws login` opens your
browser and signs in with your AWS console credentials, with no access keys to copy. Use the bucket's region, then run the check again:

```bash
aws login --region "$AWS_REGION"
aws sts get-caller-identity
```

The check must print your account before you go on. A login lasts a limited time, so if a command in step 8 later fails with an expired token, run `aws login`
again. If `aws login` is not found, step 5 did not get you to AWS CLI 2.32: check `aws --version`. If your organization signs in through single sign-on, run
`aws configure sso` instead; with plain access keys, `aws configure`.

## Part B: Give the data flow access to the bucket

**8. Create a read-only AWS key for this bucket.** The data flow reads the bucket with this key, so give it nothing more than listing and reading `logs/`:
no write, no delete, no other bucket. This creates an IAM user with that one policy, then a key for it. The last command prints the key id and the secret
once: copy both before you clear the terminal.

```bash
export IAM_USER="ads-s3-gzip-reader"
POLICY_FILE=$(mktemp)
cat > "$POLICY_FILE" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::$BUCKET_NAME",
      "Condition": {"StringLike": {"s3:prefix": ["logs", "logs/*"]}}
    },
    {
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::$BUCKET_NAME/logs/*"
    }
  ]
}
EOF
aws iam create-user --user-name "$IAM_USER"
aws iam put-user-policy --user-name "$IAM_USER" --policy-name read-logs-only --policy-document "file://$POLICY_FILE"
rm -f "$POLICY_FILE"
aws iam create-access-key --user-name "$IAM_USER" --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text
```

If a name in this step is already taken (`EntityAlreadyExists`), set `IAM_USER` to another one and run the block again.

**9. Store the key as a secret (DigitalOcean dashboard).** Open **Agent Data Services**, go to your workspace, open **Settings**, click **Create spaces secret**, name it
`my-input-s3`, and add the access key id and the secret key from step 8 there. The form says "spaces", but it takes an AWS key. The name must be exactly
`my-input-s3`, because the manifest looks the secret up by that name; any other name fails the deploy with `secret ref not found`. The form names the keys for
you, so you do not type them.

```
DigitalOcean dashboard -> Agent Data Services -> your workspace -> Settings -> Create spaces secret
```

## Part C: Configure the project

**10. Put your values in the manifest and set the table name.** `data-flow.toml` ships with `name = "pipeline-py-s3-gzip"`, `bucket = "your-bucket-name"` and the
`us-west-2` endpoint. One command sets `name`, `input.bucket`, `input.s3_endpoint` and `input.s3_region`, and writes `TABLE_NAME` into `table = ...` in
`s3_gzip/pipeline.py` and into `s3_gzip/sink.ddl`: the two places that must agree. S3 signs requests with the bucket's own region, so `s3_endpoint` and
`s3_region` must both match step 1 (unlike Spaces, where `s3_region` stays `us-east-1`). Run it **before** you deploy: the names are packed into the data flow,
and a running data flow keeps its table. It keeps a backup of the manifest (`data-flow.toml.bak`; each run replaces it). It stops with one `error:` line,
changing nothing, if a value is empty or the table name is empty or has a capital letter, a hyphen or a space. Do not commit the edited files. Do not run it
again with another table name for a data flow that is already deployed: an update switches the sink to the new table and does not read the bucket again, so
the new table stays empty. Delete the data flow (step 19) first, then deploy. `input.s3_endpoint` cannot be changed on a running data flow either: if it is
wrong, delete the data flow and deploy it again.

```bash
python3 scripts/configure.py --table "$TABLE_NAME" name="$DATA_FLOW_NAME" input.bucket="$BUCKET_NAME" \
  input.s3_endpoint="https://s3.$AWS_REGION.amazonaws.com" input.s3_region="$AWS_REGION"
```

**11. Check the edits.** It should show your data flow name, your bucket, your S3 endpoint and region, and your table name (both table lines). Then have the
CLI check the manifest by the rules the API applies. It works offline, and prints nothing when the file is fine.

```bash
grep -nE '^(name|bucket|s3_endpoint|s3_region) =' data-flow.toml
grep -n '    table = ' s3_gzip/pipeline.py; head -1 s3_gzip/sink.ddl
ads-data-flow manifest verify data-flow.toml
```

**12. Optional: run the tests.** They use a stand-in for `CsvObjectSource` and need no network or ADS, so a pass shows the entry's logic, not that the
deploy will work.

```bash
python3 -m venv .venv && .venv/bin/pip install pyarrow
.venv/bin/python -m unittest discover -s tests -v
```

## Part D: Deploy

**13. Check that the CLI can reach your workspace.** It lists the data flows in the workspace, so an empty list is fine. A
wrong token, workspace UUID or region shows up here.

```bash
ads-data-flow list
```

**14. Optional: build the package.** `deploy` builds the same package in memory, so this only lets you see what will be
uploaded. It writes `pipeline.tar.zst` here, holding `bin/pipeline` and `src/s3_gzip/` with both `.ddl` files, and
nothing else.

```bash
ads-data-flow build . && ls -l pipeline.tar.zst
```

**15. Deploy.** Builds the package and creates the data flow in your workspace, then waits until it is `active` with the
package attached. If a data flow with this name already exists, `deploy` updates it instead. `active` does not show the
code is running: steps 16 to 18 do.

```bash
ads-data-flow deploy --wait
```

## Part E: Test the deployed data flow

**16. Check the tables.** Allow a minute. In **Agent Data Services** → your workspace, the Catalog shows your table with 36 columns (the 33 from the log, plus
`object_key`, `line_no` and `ingested_at`) and `<table>_failed` with 7. Open the **Semantic Query** tab and paste one query at a time into the SQL
editor, then click **Run query**. The Query tab needs the full path, `tabular.<schema>.<table>`, where `<schema>` is your workspace name with
`-` written as `_` (workspace `rchauhan-ads-workspace` is `tabular.rchauhan_ads_workspace.<table>`). The dataset tree on the left shows it. Replace `<schema>`
and `<table>` with your own names in every query below.

```sql
SELECT object_key, line_no, ray_id, client_request_host, edge_response_status, edge_start_timestamp FROM tabular.<schema>.<table> ORDER BY object_key, line_no
```

```sql
SELECT source_ref, source_offset, failed_reason, failed_stage FROM tabular.<schema>.<table>_failed ORDER BY source_ref, source_offset
```

The first query returns 10 rows: 6 from `logs/requests_clean.log.gz` (`line_no` 0 to 5) and 4 from `logs/requests_with_errors.log.gz` (`line_no` 0 to 3). The
second returns 5 rows, all from `logs/requests_with_errors.log.gz`, with the reasons in the table at the top of this page. `source_offset` is the
0-based line number, so it runs 4 to 8. `failed_raw` is the original line, and the Query tab shows it base64-encoded. Upload more `.log.gz` files with the same
fields under `logs/` and your table grows by their good lines. A new file is picked up within the poll interval.

**17. Check that the rows landed and the failures were captured.** Use the **Semantic Query** tab as in step 16: one query at a time, with your own
`<schema>` and `<table>`. Every query is limited to the two sample files, so other objects in your bucket do not change an answer. Write the full
name every time: the Query tab sends your text as it is.

Rows per file. Expected: `logs/requests_clean.log.gz` 6 and `logs/requests_with_errors.log.gz` 4.

```sql
SELECT object_key, count(*) AS requests FROM tabular.<schema>.<table> WHERE object_key IN ('logs/requests_clean.log.gz', 'logs/requests_with_errors.log.gz') GROUP BY object_key ORDER BY object_key
```

Failed lines from the clean file. Expected: 0.

```sql
SELECT count(*) AS failed_lines FROM tabular.<schema>.<table>_failed WHERE source_ref = 'logs/requests_clean.log.gz'
```

Why each line of the error file failed. Expected: five rows, one each: `author.bad_value.edge_response_status`, `author.duplicate_in_object`,
`author.malformed_json`, `author.missing_ray_id` and `author.not_an_object`.

```sql
SELECT failed_reason, count(*) AS n FROM tabular.<schema>.<table>_failed WHERE source_ref = 'logs/requests_with_errors.log.gz' GROUP BY failed_reason ORDER BY failed_reason
```

Which stage refused them. Expected: `entry` 5. The Source (the line reader) refused none: a line it cannot cut would show as `source`.

```sql
SELECT failed_stage, count(*) AS n FROM tabular.<schema>.<table>_failed WHERE source_ref = 'logs/requests_with_errors.log.gz' GROUP BY failed_stage ORDER BY failed_stage
```

The failed lines in full. Expected: five rows, `source_offset` 4 to 8 (lines 5 to 9 of the file, counting from 0), all `entry`. `failed_raw` is the original line and shows base64-encoded.

```sql
SELECT failed_reason, failed_stage, source_offset FROM tabular.<schema>.<table>_failed WHERE source_ref = 'logs/requests_with_errors.log.gz' ORDER BY source_offset
```

Is any `ray_id` stored twice within a file? Expected: 0. (Across the two files, four are: see step 18.)

```sql
SELECT count(*) AS repeated FROM (SELECT object_key, ray_id FROM tabular.<schema>.<table> WHERE object_key IN ('logs/requests_clean.log.gz', 'logs/requests_with_errors.log.gz') GROUP BY object_key, ray_id HAVING count(*) > 1) AS d
```

If the counts are exactly double (20 and 10, for example), the table already held the sample rows, for example from an earlier deploy on the same
table: delete the data flow (step 19), then run step 10 with a new `TABLE_NAME` and deploy again.

**18. Ask questions of the data.** These are questions to run the same way. Each shows the answer you should get for the two sample files. Then change a
filter, or upload a `.log.gz` of your own under `logs/` with the same fields and ask about that.

Requests per host. Expected: `api.example.com` 4, `cloud.example.com` 3, `www.example.com` 3.

```sql
SELECT client_request_host, count(*) AS requests FROM tabular.<schema>.<table> WHERE object_key IN ('logs/requests_clean.log.gz', 'logs/requests_with_errors.log.gz') GROUP BY client_request_host ORDER BY client_request_host
```

Responses by status. Expected: `200` 8, `404` 2.

```sql
SELECT edge_response_status, count(*) AS n FROM tabular.<schema>.<table> WHERE object_key IN ('logs/requests_clean.log.gz', 'logs/requests_with_errors.log.gz') GROUP BY edge_response_status ORDER BY edge_response_status
```

Average time to first byte per host. Expected: `api.example.com` 22.5, `cloud.example.com` 23.0, `www.example.com` 24.0.

```sql
SELECT client_request_host, round(avg(edge_time_to_first_byte_ms), 1) AS avg_ttfb_ms FROM tabular.<schema>.<table> WHERE object_key IN ('logs/requests_clean.log.gz', 'logs/requests_with_errors.log.gz') GROUP BY client_request_host ORDER BY client_request_host
```

Distinct requests, once repeated `ray_id`s are counted once. Expected: 6, although the table holds 10 rows.

```sql
SELECT count(DISTINCT ray_id) AS requests FROM tabular.<schema>.<table> WHERE object_key IN ('logs/requests_clean.log.gz', 'logs/requests_with_errors.log.gz')
```

Which `ray_id`s are in both files. Expected: four, `ray0001` to `ray0004`.

```sql
SELECT ray_id FROM tabular.<schema>.<table> WHERE object_key IN ('logs/requests_clean.log.gz', 'logs/requests_with_errors.log.gz') GROUP BY ray_id HAVING count(DISTINCT object_key) > 1 ORDER BY ray_id
```

Who called, without the address. Expected: 6 distinct values of `client_ip`, each a 16-character hash, none an IP.

```sql
SELECT count(DISTINCT client_ip) AS clients, max(length(client_ip)) AS hash_length FROM tabular.<schema>.<table> WHERE object_key IN ('logs/requests_clean.log.gz', 'logs/requests_with_errors.log.gz')
```

Total bytes served. Expected: 31000.

```sql
SELECT sum(edge_response_bytes) AS bytes FROM tabular.<schema>.<table> WHERE object_key IN ('logs/requests_clean.log.gz', 'logs/requests_with_errors.log.gz')
```

## Part F: Clean up

**19. Delete the data flow.** This finds its UUID by its name, asks you to confirm, then deletes it. It removes the data flow and keeps its tables and
their rows: emptying the bucket does not clear them, and a redeploy appends every row again. For a clean run, delete the data
flow, then run step 10 again with a new `TABLE_NAME` and deploy.

```bash
FLOW_UUID=$(ads-data-flow list -o json | jq -r --arg n "$DATA_FLOW_NAME" '.[] | select(.name == $n) | .uuid'); echo "$FLOW_UUID"
test -n "$FLOW_UUID" && ads-data-flow delete "$FLOW_UUID" --wait
```

Or without `jq`: list your data flows, copy the UUID of yours from the `UUID` column, and delete it by hand. `delete` asks you to confirm with `y`,
and `--wait` returns once it is gone. `ads-data-flow list` should then show an empty list.

```bash
ads-data-flow list
ads-data-flow delete <uuid> --wait
ads-data-flow list
```

**20. Delete the AWS key and user.** The key can read your bucket for as long as it exists, so do not leave it behind. Delete the policy, the key and the
user, in that order. In a new terminal, set `IAM_USER` to the name you used in step 8 first, and sign in again if needed (step 7). Then delete the `my-input-s3`
secret in the workspace's **Settings**.

```bash
aws iam delete-user-policy --user-name "$IAM_USER" --policy-name read-logs-only
for key in $(aws iam list-access-keys --user-name "$IAM_USER" --query 'AccessKeyMetadata[].AccessKeyId' --output text); do
  aws iam delete-access-key --user-name "$IAM_USER" --access-key-id "$key"
done
aws iam delete-user --user-name "$IAM_USER"
```

**21. Empty and delete the bucket (AWS console).** Only if you made it for this guide: empty it, then delete it. Otherwise delete just the `logs/` folder you
uploaded.

**22. Forget your token.** Then close the terminal, so it leaves its history too.

```bash
unset DIGITALOCEAN_TOKEN
```

## Using real Logpush files

- **Memory and disk.** The object is fetched and decoded to scratch disk, and the entry sees one unit at a time (at most `max_records` lines; 100000 here),
  so memory does not grow with the object. The decoded object counts against `max_bytes`, which the runtime derives as 25% of the VM's memory up to 4 GiB;
  `mv-8vcpu-16gb` gives about 4 GiB, which should fit a real Logpush object (about 85 MB gzipped, 1.6 GB and 560k lines unzipped). The scratch disk must hold the
  compressed and the decoded copy. The sample files in this guide are a few hundred bytes: a real object has not been run through this example.
- **More tables from the same files.** The SDK runs one table per data flow. To load more columns of the same Logpush files (say a security table), copy this
  project, change `FIELDS` and `sink.ddl`, and deploy it as its own data flow reading the same prefix.
- **`ClientIP` is personal data.** The entry hashes it before it lands, which hides the address from a casual reader but is not anonymous (see Files). Keep the
  bucket private and the read-only key scoped to the prefix, as in step 8.
