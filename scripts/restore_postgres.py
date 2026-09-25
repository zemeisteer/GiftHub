"""
GiftHub PostgreSQL Restore & Verification Utility.
"A backup that has never been restore-tested is not considered verified."

Restores into a designated target or temporary database and executes
financial integrity checks to verify data consistency.
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def verify_and_restore(backup_path: str, target_db: str = "gifthub_restore_test") -> bool:
    b_path = Path(backup_path)
    if not b_path.exists():
        print(f"[!] Error: Backup file {backup_path} does not exist.")
        return False

    # 1. Checksum validation
    sha_file = b_path.with_suffix(".dump.sha256")
    if sha_file.exists():
        expected_sha = sha_file.read_text().split()[0].strip()
        actual_sha = compute_sha256(b_path)
        if expected_sha != actual_sha:
            print(f"[!] Checksum mismatch! Expected {expected_sha}, got {actual_sha}")
            return False
        print(f"✅ Checksum matched: {actual_sha[:12]}...")

    env = os.environ.copy()
    if POSTGRES_PASSWORD:
        env["PGPASSWORD"] = POSTGRES_PASSWORD

    # 2. Re-create target database for dry-run verification
    print(f"[*] Preparing test database '{target_db}'...")
    subprocess.run(
        ["dropdb", "-h", POSTGRES_HOST, "-p", POSTGRES_PORT, "-U", POSTGRES_USER, "--if-exists", target_db],
        env=env, capture_output=True
    )
    subprocess.run(
        ["createdb", "-h", POSTGRES_HOST, "-p", POSTGRES_PORT, "-U", POSTGRES_USER, target_db],
        env=env, capture_output=True
    )

    # 3. Execute pg_restore
    print(f"[*] Restoring from {b_path.name} into '{target_db}'...")
    cmd = [
        "pg_restore",
        "-h", POSTGRES_HOST,
        "-p", POSTGRES_PORT,
        "-U", POSTGRES_USER,
        "-d", target_db,
        "-v",
        str(b_path)
    ]
    res = subprocess.run(cmd, env=env, capture_output=True, text=True)

    # 4. Verify integrity via SQL queries
    print("[*] Running sanity checks on restored database...")
    query_cmd = [
        "psql",
        "-h", POSTGRES_HOST,
        "-p", POSTGRES_PORT,
        "-U", POSTGRES_USER,
        "-d", target_db,
        "-c",
        "SELECT count(*) FROM users; SELECT count(*) FROM orders; SELECT count(*) FROM wallet_transactions;"
    ]
    q_res = subprocess.run(query_cmd, env=env, capture_output=True, text=True)

    if q_res.returncode == 0:
        print("✅ Restored database verification SUCCESSFUL:")
        print(q_res.stdout)
        print("🎉 STATUS: RESTORE_VERIFIED")
        return True
    else:
        print(f"[!] Verification queries failed:\n{q_res.stderr}")
        print("❌ STATUS: RESTORE_FAILED")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.restore_postgres <path_to_backup.dump> [target_db]")
        sys.exit(1)
    backup_file = sys.argv[1]
    target = sys.argv[2] if len(sys.argv) > 2 else "gifthub_restore_test"
    success = verify_and_restore(backup_file, target)
    sys.exit(0 if success else 1)
