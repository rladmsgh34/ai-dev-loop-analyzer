#!/bin/bash
set -euo pipefail

# Smoke test for ai-dev-loop-analyzer
URL="${BASE_URL:-https://ai-dev-loop-analyzer.rladmsgh34.org}"

echo "🔍 Smoking testing: $URL"

# Check if the main page returns 200
if curl -sfI "$URL" > /dev/null; then
    echo "✅ Smoke test passed: $URL is accessible"
else
    echo "❌ Smoke test failed: $URL is not accessible"
    exit 1
fi
