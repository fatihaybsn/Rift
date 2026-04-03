#!/usr/bin/env bash
set -e

echo "Waiting for API Change Radar to be healthy..."
for i in {1..30}; do
  if curl -s http://localhost:8000/healthz | grep '"status":"healthy"' >/dev/null; then
    echo "Service is healthy!"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "Timeout waiting for service."
    exit 1
  fi
  sleep 1
done

echo
echo "Creating sample run..."
# Write dummy specs to /tmp and upload
echo '{"openapi": "3.0.0", "info": {"title": "Old API", "version": "1.0.0"}, "paths": {}}' > /tmp/old_spec.json
echo '{"openapi": "3.0.0", "info": {"title": "New API", "version": "1.0.1"}, "paths": {"/pets": {"get": {"responses": {"200": {"description": "OK"}}}}}}' > /tmp/new_spec.json

RESPONSE=$(curl -s -X POST http://localhost:8000/api/v1/runs \
  -F "specs=@/tmp/old_spec.json;type=application/json" \
  -F "specs=@/tmp/new_spec.json;type=application/json" \
  -F "changelog_text=Added pets endpoint")

RUN_ID=$(echo "$RESPONSE" | grep -o '"run_id":"[^"]*' | cut -d'"' -f4)

if [ -z "$RUN_ID" ]; then
  echo "Failed to create run. Response:"
  echo "$RESPONSE"
  exit 1
fi

echo "Created Run ID: $RUN_ID"
echo

echo "Waiting for run to be processed automatically in the background..."
for i in {1..30}; do
  STATUS_RESPONSE=$(curl -s "http://localhost:8000/api/v1/runs/${RUN_ID}")
  STATUS=$(echo "$STATUS_RESPONSE" | grep -o '"status":"[^"]*' | cut -d'"' -f4)
  
  if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then
    echo "Run finished with status: $STATUS"
    break
  fi
  
  if [ "$i" -eq 30 ]; then
    echo "Timeout waiting for run to complete. Last response:"
    echo "$STATUS_RESPONSE"
    exit 1
  fi
  sleep 1
done

echo
echo "Fetching final report..."
curl -s "http://localhost:8000/api/v1/reports/${RUN_ID}?format=markdown"

echo ""
echo "Smoke test complete!"
