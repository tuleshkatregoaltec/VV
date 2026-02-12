#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
DATA_DIR="$PROJECT_ROOT/data/new"

echo "=== Loading local data into ClickHouse ==="
echo "Project root: $PROJECT_ROOT"
echo "Data directory: $DATA_DIR"

# Check if docker-compose is running
if ! docker ps | grep -q vitevue-clickhouse; then
    echo "Error: ClickHouse container is not running"
    echo "Start it with: docker-compose up -d clickhouse"
    exit 1
fi

# Copy CSV files into ClickHouse container (only if they don't exist or are different)
echo ""
echo "Checking CSV files in ClickHouse container..."
docker exec vitevue-clickhouse mkdir -p /var/lib/clickhouse/user_files

for csv_file in transactions.csv rent_contracts.csv projects.csv buildings.csv units.csv land_registry.csv developers.csv; do
    if [ -f "$DATA_DIR/$csv_file" ]; then
        # Check if file exists in container
        if docker exec vitevue-clickhouse test -f "/var/lib/clickhouse/user_files/$csv_file" 2>/dev/null; then
            echo "  $csv_file already exists, skipping..."
        else
            echo "  Copying $csv_file..."
            docker cp "$DATA_DIR/$csv_file" vitevue-clickhouse:/var/lib/clickhouse/user_files/
        fi
    else
        echo "  Warning: $csv_file not found in $DATA_DIR"
    fi
done

echo ""
echo "CSV files copied successfully!"
echo ""
echo "Creating ClickHouse tables..."

# Create tables from schemas.sql
docker exec vitevue-clickhouse clickhouse-client --database=vitevue --multiquery < "$SCRIPT_DIR/schemas.sql"

echo ""
echo "Tables created successfully!"
echo ""
echo "Running insert script..."

# Run the Python insert script
cd "$PROJECT_ROOT/backend"
uv run scripts/insert/insert_hybrid.py

echo ""
echo "=== Data loading complete! ==="
