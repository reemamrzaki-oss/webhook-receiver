#!/bin/bash

IP=${1:-localhost}
PORT=${2:-8443}

if [ "$IP" = "localhost" ]; then
  echo "🧪 Local tests on http://$IP:$PORT"
else
  echo "🧪 VPS tests on http://$IP:$PORT"
fi

# Health
curl -s -w "\nHTTP: %{http_code}\n" http://$IP:$PORT/health

# Simple POST
RESPONSE=$(curl -s -w "\nHTTP: %{http_code}\n" -X POST http://$IP:$PORT/webhook -d 'plain text body')
ID=$(echo $RESPONSE | grep -o '"request_id": "[^"]*"' | cut -d'"' -f4)
echo "POST plain: $ID"

# JSON POST
RESPONSE=$(curl -s -w "\nHTTP: %{http_code}\n" -X POST -H "Content-Type: application/json" http://$IP:$PORT/webhook -d '{"json":"data"}')
ID=$(echo $RESPONSE | grep -o '"request_id": "[^"]*"' | cut -d'"' -f4)
echo "POST JSON: $ID"

# GET query
curl -s -w "\nHTTP: %{http_code}\n" "http://$IP:$PORT/webhook?get=param"

echo "\n✅ Tests complete. Check files /opt/webhook-data (VPS) or data.json"