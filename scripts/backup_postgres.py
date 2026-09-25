"""
GiftHub Automated PostgreSQL Backup Utility.
Creates compressed, verified backups with SHA-256 checksums and automatic rotation.
"""

import hashlib
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "./backups"))
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "gifthub")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "7"))


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def run_backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%SZ")
    backup_file = BACKUP_DIR / f"gifthub_backup_{timestamp}.dump"

    env = os.environ.copy()
    if POSTGRES_PASSWORD:
        env["PGPASSWORD"] = POSTGRES_PASSWORD

    cmd = [
        "pg_dump",
        "-h",
        POSTGRES_HOST,
        "-p",
        POSTGRES_PORT,
        "-U",
        POSTGRES_USER,
        "-d",
        POSTGRES_DB,
        "-F",
        "c",  # Custom format (compressed, supports pg_restore)
        "-b",  # Include large objects
        "-v",
        "-f",
        str(backup_file),
    ]

    print(f"[*] Starting PostgreSQL backup for '{POSTGRES_DB}' -> {backup_file}...")
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)

    if res.returncode != 0:
        print(f"[!] pg_dump failed with return code {res.returncode}:\n{res.stderr}")
        sys.exit(res.returncode)

    file_size_mb = backup_file.stat().st_size / (1024 * 1024)
    sha256 = compute_sha256(backup_file)
    checksum_file = backup_file.with_suffix(".dump.sha256")
    checksum_file.write_text(f"{sha256}  {backup_file.name}\n", encoding="utf-8")

    print("✅ Backup completed successfully:")
    print(f"   File:     {backup_file}")
    print(f"   Size:     {file_size_mb:.2f} MB")
    print(f"   SHA-256:  {sha256}")

    # Rotate old backups
    cleanup_old_backups()
    return backup_file


def cleanup_old_backups():
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - (RETENTION_DAYS * 86400)
    for p in BACKUP_DIR.glob("gifthub_backup_*.dump*"):
        if p.stat().st_mtime < cutoff:
            print(f"[*] Rotating out expired backup: {p.name}")
            p.unlink()


if __name__ == "__main__":
    run_backup()
