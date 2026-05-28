# backup.py - SAOS Cognitive Backup & Git-Archiver Daemon
import os
import sys
import time
import gzip
import shutil
import logging
import subprocess
from datetime import datetime

# Configure clean terminal logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("saos.backup")

# ── Cloud Credentials & Environment variables ──────────────────────────────────
R2_ACCESS_KEY = os.getenv("R2_ACCESS_KEY", "")
R2_SECRET_KEY = os.getenv("R2_SECRET_KEY", "")
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_BUCKET = os.getenv("R2_BUCKET", "saos-backups")

GITHUB_PAT = os.getenv("GITHUB_PAT", "")
GITHUB_USER = os.getenv("GITHUB_USER", "")
ACTIVE_REPO_NAME = os.getenv("GITHUB_REPO", "saos-backups-part-1")

REDIS_DATA_DIR = "/data"
REDIS_DUMP_PATH = os.path.join(REDIS_DATA_DIR, "dump.rdb")
COMPRESSED_DUMP_PATH = os.path.join(REDIS_DATA_DIR, "dump.rdb.gz")

# ── Cloudflare R2 Sync Helper ─────────────────────────────────────────────────
def compress_dump() -> bool:
    """Compresses dump.rdb to gzip with maximum compression (level 9)."""
    if not os.path.exists(REDIS_DUMP_PATH):
        logger.info("No active Redis dump.rdb file found to compress.")
        return False

    try:
        logger.info(f"Compressing {REDIS_DUMP_PATH} to {COMPRESSED_DUMP_PATH}...")
        with open(REDIS_DUMP_PATH, 'rb') as f_in:
            with gzip.open(COMPRESSED_DUMP_PATH, 'wb', compresslevel=9) as f_out:
                shutil.copyfileobj(f_in, f_out)
        logger.info("Successfully compressed Redis database dump!")
        return True
    except Exception as e:
        logger.error(f"Failed to compress Redis database dump: {e}")
        return False

# ── Cloudflare R2 Sync Helper ─────────────────────────────────────────────────
def upload_to_r2() -> bool:
    """Uploads pre-compressed dump.rdb.gz to Cloudflare R2 S3 bucket."""
    if not (R2_ACCESS_KEY and R2_SECRET_KEY and R2_ACCOUNT_ID):
        logger.warning("Cloudflare R2 credentials missing. Skipping R2 swap upload.")
        return False

    if not os.path.exists(COMPRESSED_DUMP_PATH):
        logger.info("No compressed dump.rdb.gz found to upload to R2.")
        return False

    try:
        # Upload to S3-compatible R2 endpoint
        import boto3
        from botocore.client import Config

        r2_endpoint = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
        s3 = boto3.client(
            "s3",
            endpoint_url=r2_endpoint,
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY,
            config=Config(signature_version="s3v4")
        )

        logger.info(f"Uploading compressed cache to R2 bucket '{R2_BUCKET}'...")
        s3.upload_file(COMPRESSED_DUMP_PATH, R2_BUCKET, "vault/redis/dump.rdb.gz")
        logger.info("Successfully updated Cloudflare R2 state swap partition!")
        return True
    except Exception as e:
        logger.error(f"Failed to sync with R2 swap partition: {e}")
        return False

# ── GitHub Git-Archiver & Rollover Engine ──────────────────────────────────────
def run_git_command(args: list, cwd: str = REDIS_DATA_DIR) -> str:
    """Executes a subprocess git command and returns the stdout result."""
    result = subprocess.run(
        args,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=True
    )
    return result.stdout.strip()

def check_github_repo_size(repo_name: str) -> int:
    """Queries GitHub REST API to get repository size in Kilobytes."""
    if not (GITHUB_PAT and GITHUB_USER):
        return 0
    try:
        import urllib.request
        import json
        url = f"https://api.github.com/repos/{GITHUB_USER}/{repo_name}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"token {GITHUB_PAT}")
        req.add_header("Accept", "application/vnd.github.v3+json")
        req.add_header("User-Agent", "SAOS-Backup-Daemon")

        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode())
            size_kb = data.get("size", 0)
            logger.info(f"Active GitHub backup repo size: {size_kb} KB ({size_kb / 1024:.2f} MB)")
            return size_kb
    except Exception as e:
        logger.error(f"Failed to query repository size: {e}")
        return 0

def create_new_github_repo(repo_name: str) -> bool:
    """Programmatically creates a new private GitHub repository via REST API."""
    logger.info(f"Creating fresh private GitHub repository: '{repo_name}'...")
    try:
        import urllib.request
        import json
        url = "https://api.github.com/user/repos"
        payload = json.dumps({
            "name": repo_name,
            "private": True,
            "description": "SAOS Database Swap & Transcripts cold-archive partition.",
            "auto_init": False
        }).encode("utf-8")

        req = urllib.request.Request(url, data=payload)
        req.add_header("Authorization", f"token {GITHUB_PAT}")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/vnd.github.v3+json")
        req.add_header("User-Agent", "SAOS-Backup-Daemon")

        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 201:
                logger.info(f"Successfully generated new private repository '{repo_name}'!")
                return True
        return False
    except Exception as e:
        logger.critical(f"GitHub repository generation failed: {e}")
        return False

def sync_to_github():
    """Commits and pushes the latest database snapshot to the active private repository."""
    global ACTIVE_REPO_NAME

    if not (GITHUB_PAT and GITHUB_USER):
        logger.warning("GitHub credentials missing. Skipping Git-Archiver backup.")
        return

    # Check if active repo has filled up past 800MB (819,200 KB)
    current_size_kb = check_github_repo_size(ACTIVE_REPO_NAME)
    if current_size_kb >= 800000:
        logger.warning(f"Active repository '{ACTIVE_REPO_NAME}' is nearing 800MB limit. Running rollover...")
        # Increment index
        try:
            parts = ACTIVE_REPO_NAME.split("-part-")
            base = parts[0]
            num = int(parts[1]) if len(parts) > 1 else 1
            new_repo_name = f"{base}-part-{num + 1}"
        except Exception:
            new_repo_name = f"{ACTIVE_REPO_NAME}-part-2"

        # Create new repo and swap remote
        if create_new_github_repo(new_repo_name):
            ACTIVE_REPO_NAME = new_repo_name
            # Re-initialize git origin
            try:
                run_git_command(["git", "remote", "remove", "origin"])
            except Exception:
                pass
            
            origin_url = f"https://{GITHUB_USER}:{GITHUB_PAT}@github.com/{GITHUB_USER}/{new_repo_name}.git"
            run_git_command(["git", "remote", "add", "origin", origin_url])
            logger.info(f"Swarm backup targets successfully rolled over to new remote repository: {new_repo_name}")

    if not os.path.exists(COMPRESSED_DUMP_PATH):
        return

    try:
        # Initialize Git repo inside data directory if not already created
        if not os.path.exists(os.path.join(REDIS_DATA_DIR, ".git")):
            logger.info("Initializing Git repository inside /data directory...")
            run_git_command(["git", "init"])
            run_git_command(["git", "config", "user.name", "saos-backup-daemon"])
            run_git_command(["git", "config", "user.email", "saos-daemon@olympus.internal"])
            
            # Add secure remote
            origin_url = f"https://{GITHUB_USER}:{GITHUB_PAT}@github.com/{GITHUB_USER}/{ACTIVE_REPO_NAME}.git"
            run_git_command(["git", "remote", "add", "origin", origin_url])

        # Commit and force-push the snapshot
        logger.info("Archiving snapshot to private GitHub repository...")
        shutil.copy2(COMPRESSED_DUMP_PATH, os.path.join(REDIS_DATA_DIR, "dump.rdb.gz"))
        
        # Write small history commit
        run_git_command(["git", "add", "dump.rdb.gz"])
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        run_git_command(["git", "commit", "-m", f"SAOS state sync snapshot: {timestamp} [skip ci]"])
        
        # Push to main
        run_git_command(["git", "branch", "-M", "main"])
        run_git_command(["git", "push", "-f", "origin", "main"])
        logger.info("GitHub Git-Archiver state commit successful!")
    except Exception as e:
        logger.error(f"Git-Archiver sync failed: {e}")

# ── Daemon Entrypoint Loop ────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("SAOS Cognitive Backup Sync Daemon is starting...")
    # Sleep 30 seconds on initial boot to let Redis populate dumps
    time.sleep(30)
    
    while True:
        logger.info("Triggering scheduled cognitive backup sequence...")
        
        # 1. Compress active database dump
        compressed_ok = compress_dump()
        
        if compressed_ok:
            # 2. Upload compressed dump to Cloudflare R2 independently
            upload_to_r2()
            
            # 3. Push compressed dump to Private GitHub Archiver independently
            sync_to_github()
            
        # Run every 5 minutes (300 seconds)
        time.sleep(300)
