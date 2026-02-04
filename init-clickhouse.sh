#!/bin/bash
set -e

# Wait for ClickHouse to be ready
until clickhouse-client --query "SELECT 1" > /dev/null 2>&1; do
  echo "Waiting for ClickHouse to be ready..."
  sleep 1
done

echo "ClickHouse is ready. Creating database..."

clickhouse-client --query "CREATE DATABASE IF NOT EXISTS vitevue"

echo "ClickHouse initialization complete."
