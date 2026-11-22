#!/usr/bin/env bash
# Deploy to EC2: copy this checkout up, then restart the containers.
#
#   ./deploy.sh
#
# Reads DEPLOY_HOST and DEPLOY_KEY from the environment or from .env in the repo root.
# .env is never copied: install it on the server by hand, at ~/sec-check/.env.
set -euo pipefail

cd "$(dirname "$0")"
[ -f .env ] && . ./.env

HOST=${DEPLOY_HOST:?Set DEPLOY_HOST}
KEY=${DEPLOY_KEY:?Set DEPLOY_KEY}
DIR=sec-check
# Enough to rebuild every image from fresh base images (about 1.2 GB), with some to spare
MIN_FREE_MB=1500

ssh_() { ssh -i "$KEY" "$HOST" "$@"; }

echo "==> Setting up host (no-op after the first run)"
ssh_ 'bash -s' <<'EOF'
set -e
if ! command -v docker >/dev/null; then
  sudo dnf install -y docker
  sudo systemctl enable --now docker
fi
# Amazon Linux's docker package has no compose plugin and a buildx too old for compose.
# Plugins here take precedence over the packaged ones in /usr/libexec/docker/cli-plugins.
plugins=/usr/local/lib/docker/cli-plugins
sudo mkdir -p $plugins
if [ ! -x $plugins/docker-compose ]; then
  sudo curl -fsSL -o $plugins/docker-compose \
    https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64
  sudo chmod +x $plugins/docker-compose
fi
if [ ! -x $plugins/docker-buildx ]; then
  sudo curl -fsSL -o $plugins/docker-buildx \
    https://github.com/docker/buildx/releases/download/v0.17.1/buildx-v0.17.1.linux-amd64
  sudo chmod +x $plugins/docker-buildx
fi
# The instance has ~1 GB of RAM; builds and MySQL need swap
if [ ! -f /swapfile ]; then
  sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  echo '/swapfile none swap defaults 0 0' | sudo tee -a /etc/fstab >/dev/null
fi
EOF

# After setup, which installs Docker and may create the swap file. Nothing is copied or stopped
# until this passes, so a full disk leaves the running site alone.
echo "==> Checking disk space"
free_mb=$(ssh_ 'df --output=avail -BM /var/lib/docker | tail -n 1 | tr -dc 0-9')
# Not `-lt`: if df printed something unexpected, this fails too
if ! [ "$free_mb" -ge "$MIN_FREE_MB" ]; then
  echo "Not enough disk space on the server: ${free_mb:-unknown} MB free, need $MIN_FREE_MB MB." >&2
  echo "'sudo docker builder prune' on the server clears old build cache. Disk use now:" >&2
  ssh_ 'df -h /var/lib/docker; sudo docker system df' >&2 || true
  exit 1
fi
echo "$free_mb MB free"

echo "==> Copying files"
# Excluding .env also keeps --delete from removing the server's copy
rsync -az --delete -e "ssh -i $KEY" \
  --exclude .env --exclude .git --exclude node_modules --exclude dist --exclude .venv \
  --exclude __pycache__ --exclude .ruff_cache \
  ./ "$HOST:$DIR/"
ssh_ "test -f $DIR/.env" || { echo "Missing $DIR/.env on the server; copy it there first" >&2; exit 1; }

echo "==> Restarting containers"
ssh_ "cd $DIR && sudo docker compose down && sudo docker compose up -d --build && sudo docker image prune -f && sudo docker compose ps"
