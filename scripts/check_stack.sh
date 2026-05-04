#!/bin/bash
set -euo pipefail

echo "Checking FMMS stack health..."

check() {
  local name=$1
  local url=$2
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
  if [ "$code" = "200" ]; then
    echo "  ✓ $name"
  else
    echo "  ✗ $name (HTTP $code)"
  fi
}

check "geo-service"       "http://localhost:8005/healthz"
check "auth-service"      "http://localhost:8006/healthz"
check "ingestion-gateway" "http://localhost:8001/healthz"
check "telemetry-service" "http://localhost:8002/healthz"
check "rule-engine"       "http://localhost:8003/healthz"
check "alert-service"     "http://localhost:8004/healthz"
check "dashboard-bff"     "http://localhost:8080/healthz"
check "prometheus"        "http://localhost:9090/-/healthy"
check "grafana"           "http://localhost:3001/api/health"
