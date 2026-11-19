"""Write the two sample objects into testdata/: python3 scripts/make_sample.py

requests_clean.log.gz        6 good lines
requests_with_errors.log.gz  4 good lines and 5 bad ones, each for a different reason
The output is deterministic (fixed gzip mtime), so a rerun changes nothing.
"""

import gzip
import json
from pathlib import Path

TESTDATA = Path(__file__).resolve().parent.parent / "testdata"
HOSTS = ["www.example.com", "api.example.com", "cloud.example.com"]


def line(n: int, **override) -> dict:
    row = {
        "RayID": "ray%04d" % n, "EdgeStartTimestamp": "2026-11-10T00:00:%02dZ" % n,
        "EdgeEndTimestamp": "2026-11-10T00:00:%02dZ" % (n + 1), "ZoneName": "example.com",
        "ClientRequestHost": HOSTS[n % 3], "ClientRequestMethod": "GET", "ClientRequestPath": "/docs/%d" % n,
        "ClientRequestURI": "/docs/%d?x=1" % n, "ClientRequestProtocol": "HTTP/2", "ClientRequestReferer": "",
        "ClientRequestUserAgent": "curl/8.4" if n % 2 else "Mozilla/5.0", "ClientRequestBytes": 300 + n,
        "EdgeResponseStatus": 200 if n % 4 else 404, "EdgeResponseBytes": 1000 * n, "EdgeResponseBodyBytes": 900 * n,
        "EdgeResponseContentType": "text/html", "OriginResponseStatus": 200, "SecurityAction": "unknown",
        "EdgeTimeToFirstByteMs": 20 + n, "OriginResponseDurationMs": 15 + n, "ClientTCPRTTMs": 5,
        "CacheCacheStatus": "hit", "CacheResponseStatus": 200, "ClientASN": 14061, "ClientCountry": "us",
        "ClientRegionCode": "CA", "ClientDeviceType": "desktop", "ClientIP": "203.0.113.%d" % n,
        "ClientSSLProtocol": "TLSv1.3", "JA3Hash": "a" * 32, "EdgeColoID": 962, "EdgeColoCode": "SIN", "OriginIP": "",
        "WAFAttackScore": 99, "BotTags": ["verified"],  # fields outside the table are ignored
    }
    row.update(override)
    return row


def write(name: str, lines: list[bytes]) -> None:
    with open(TESTDATA / name, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        gz.write(b"\n".join(lines) + b"\n")


def main() -> None:
    enc = lambda row: json.dumps(row).encode()
    write("requests_clean.log.gz", [enc(line(n)) for n in range(1, 7)])
    write("requests_with_errors.log.gz", [
        enc(line(1)), enc(line(2)), enc(line(3)), enc(line(4)),
        b"{not json",                                              # author.malformed_json
        b'["a", "list"]',                                          # author.not_an_object
        enc(line(7, RayID="")),                                    # author.missing_ray_id
        enc(line(2)),                                              # author.duplicate_in_object
        enc(line(9, EdgeResponseStatus="teapot")),                 # author.bad_value.edge_response_status
    ])


if __name__ == "__main__":
    main()
