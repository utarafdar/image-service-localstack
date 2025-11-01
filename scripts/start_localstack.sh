#!/usr/bin/env bash
set -e

echo "Starting LocalStack..."
docker compose up -d localstack

echo "Waiting for LocalStack health..."
until curl -sS --fail http://localhost:4566/_localstack/health | grep -q '"version"'; do
  printf '.'
  sleep 3
done
echo "LocalStack is ready (checked for 'version' in response)."
