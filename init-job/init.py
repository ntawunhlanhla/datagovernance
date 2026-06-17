"""One-shot init: ensure MinIO buckets exist."""
import os
import time
import sys

from minio import Minio

ENDPOINT = os.environ.get("MINIO_ENDPOINT", "minio:9000")
ACCESS = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
SECRET = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
SECURE = os.environ.get("MINIO_SECURE", "false").lower() == "true"

BUCKETS = [
    os.environ.get("MINIO_BUCKET_RAW", "raw"),
    os.environ.get("MINIO_BUCKET_CURATED", "curated"),
    os.environ.get("MINIO_BUCKET_CONTRACTS", "contracts"),
    os.environ.get("MINIO_BUCKET_EXCEL", "excel-uploads"),
]


def main():
    client = Minio(ENDPOINT, access_key=ACCESS, secret_key=SECRET, secure=SECURE)
    # Retry until MinIO is up
    for attempt in range(60):
        try:
            client.list_buckets()
            break
        except Exception as e:
            print(f"[init] waiting for MinIO ({attempt+1}/60): {e}", flush=True)
            time.sleep(2)
    else:
        print("[init] MinIO unreachable", file=sys.stderr)
        sys.exit(1)

    for b in BUCKETS:
        if not client.bucket_exists(b):
            client.make_bucket(b)
            print(f"[init] created bucket: {b}", flush=True)
        else:
            print(f"[init] bucket exists:   {b}", flush=True)

    print("[init] done.", flush=True)


if __name__ == "__main__":
    main()
