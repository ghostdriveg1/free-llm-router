#!/bin/sh
set -e

echo "========================================================"
echo "⚡ SAOS: SUPER-AGENT OPERATING SYSTEM REDIS+WEBDIS GATEWAY"
echo "========================================================"

# 1. Create and verify the writeable data directory
mkdir -p /data
chmod 777 /data

# 2. Pull down state snapshot from Private GitHub Repository on boot
if [ -n "$GITHUB_PAT" ] && [ -n "$GITHUB_USER" ]; then
    echo "[SAOS BOOT] GitHub credentials detected. Restoring database state from private repository..."
    python3 -c "
import os, urllib.request, json, subprocess, shutil, gzip
pat = os.getenv(\"GITHUB_PAT\", \"\")
user = os.getenv(\"GITHUB_USER\", \"\")
base_repo = os.getenv(\"GITHUB_REPO\", \"saos-backups-part-1\")

try:
    req = urllib.request.Request('https://api.github.com/user/repos?sort=pushed&per_page=100')
    req.add_header('Authorization', f'token {pat}')
    req.add_header('Accept', 'application/vnd.github.v3+json')
    req.add_header('User-Agent', 'SAOS-Boot')
    
    repo_name = base_repo
    with urllib.request.urlopen(req, timeout=10) as response:
        repos = json.loads(response.read().decode())
        prefix = base_repo.split('-part-')[0] if '-part-' in base_repo else base_repo
        backup_repos = [r['name'] for r in repos if r['name'].startswith(prefix)]
        if backup_repos:
            repo_name = backup_repos[0]
            
    print(f'Found latest active backup repository: {repo_name}')
    clone_url = f'https://{user}:{pat}@github.com/{user}/{repo_name}.git'
    tmp_dir = '/tmp/saos-restore'
    
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
        
    subprocess.run(['git', 'clone', '--depth', '1', clone_url, tmp_dir], check=True)
    
    compressed_path = os.path.join(tmp_dir, 'dump.rdb.gz')
    if os.path.exists(compressed_path):
        print('Extracting database snapshot dump.rdb.gz...')
        with gzip.open(compressed_path, 'rb') as f_in:
            with open('/data/dump.rdb', 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        print('Successfully restored L1 Cache from private GitHub backup repository!')
    else:
        print('No compressed dump.rdb.gz found in backup repository. Starting fresh.')
        
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir)
except Exception as e:
    print(f'GitHub snapshot recovery failed (starting fresh): {e}')
"
else
    echo "[SAOS BOOT] GitHub credentials not configured. Starting fresh Redis database."
fi

# 3. Initialize background local Redis Server
echo "[SAOS BOOT] Starting background Redis database server..."
redis-server --dir /data --dbfilename dump.rdb --save 60 1 --protected-mode no &

# 4. Initialize background SAOS backup & Git-Archiver daemon
echo "[SAOS BOOT] Launching background backup & Git-Archiver sync daemon..."
python3 -u /app/backup.py > /var/log/backup.log 2>&1 &

# 5. Inject NANCY_REDIS_SECRET into webdis.json basic auth
if [ -n "$NANCY_REDIS_SECRET" ]; then
    echo "[SAOS BOOT] Securing Webdis endpoint using custom Basic Auth credential secrets..."
    # Format: Basic Authentication username=nancy_admin, password=NANCY_REDIS_SECRET
    # We replace webdis.json basic auth settings. In Webdis, basic auth is configured via HTTP Basic Auth in headers or JSON-RPC.
    # To implement Basic Auth in Webdis, we add the basic_auth array inside webdis.json!
    # Webdis supports "http_basic_auth": ["user:password"] at root level.
    # Let's dynamically patch webdis.json to inject the credentials!
    python3 -c "
import os, json
with open('/app/webdis.json', 'r') as f:
    data = json.load(f)
data['http_basic_auth'] = [f'nancy_admin:{os.getenv(\"NANCY_REDIS_SECRET\")}']
with open('/app/webdis.json', 'w') as f:
    json.dump(data, f, indent=2)
"
else
    echo "[WARNING] NANCY_REDIS_SECRET missing! Webdis REST server is running unsecured!"
fi

# 6. Boot Webdis REST Gateway in the foreground to keep the Hugging Face container alive
echo "[SAOS BOOT] Starting Webdis HTTP REST gateway on port 7860..."
exec webdis /app/webdis.json
