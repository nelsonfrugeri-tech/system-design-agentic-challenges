#!/usr/bin/env bash
# Official initialization: https://langfuse.com/self-hosting/administration/headless-initialization
set -euo pipefail
umask 077
langfuse_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
runtime_env="$langfuse_dir/.env"
project=agentic-challenges-langfuse
if [[ -L "$runtime_env" ]]; then
  echo 'Refusing a symlinked credential location.' >&2
  exit 1
fi
if [[ ! -f "$runtime_env" ]]; then
  if [[ -n "$(docker volume ls -q --filter label=com.docker.compose.project=$project)" ]]; then
    echo 'Existing volumes require their original .env; refusing to regenerate credentials.' >&2
    exit 1
  fi
  # Create once, atomically. Repeated starts retain initialization credentials.
  temporary_env="$(mktemp "$langfuse_dir/.env.XXXXXX")"
  trap 'rm -f -- "$temporary_env"' EXIT
  {
    printf 'LANGFUSE_BASE_URL=http://localhost:3000\nLANGFUSE_HOST=http://localhost:3000\n'
    # Local-only login, fixed on purpose so it is always the same.
    printf 'LANGFUSE_INIT_USER_EMAIL=admin@localhost.local\nLANGFUSE_INIT_USER_PASSWORD=123456\n'
    printf 'LANGFUSE_PUBLIC_KEY=pk-lf-%s\n' "$(openssl rand -hex 16)"
    printf 'LANGFUSE_SECRET_KEY=sk-lf-%s\n' "$(openssl rand -hex 32)"
    for variable in POSTGRES_PASSWORD CLICKHOUSE_PASSWORD REDIS_AUTH MINIO_ROOT_PASSWORD SALT ENCRYPTION_KEY NEXTAUTH_SECRET; do
      printf '%s=%s\n' "$variable" "$(openssl rand -hex 32)"
    done
  } > "$temporary_env"
  ln "$temporary_env" "$runtime_env"
fi
chmod 600 "$runtime_env"
docker compose --project-name "$project" --env-file "$runtime_env" -f "$langfuse_dir/compose.yaml" config --quiet
docker compose --project-name "$project" --env-file "$runtime_env" -f "$langfuse_dir/compose.yaml" up -d --wait --wait-timeout 600
printf 'Langfuse: http://localhost:3000\nCredentials: %s\n' "$runtime_env"
