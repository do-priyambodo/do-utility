#!/bin/bash
set -e

if [ ! -f "parameters.json" ]; then
  echo "❌ Error: parameters.json not found!"
  exit 1
fi

BUCKET_NAME=$(python3 -c "import json; print(json.load(open('parameters.json')).get('CONFIG_GCS_Bucket', ''))")

if [ -z "$BUCKET_NAME" ]; then
  echo "❌ Error: CONFIG_GCS_Bucket not specified in parameters.json!"
  exit 1
fi

if [ ! -f "target_urls.txt" ]; then
  echo "❌ Error: target_urls.txt local file not found! Please create target_urls.txt with one target URL per line."
  exit 1
fi

echo "🚀 Uploading target_urls.txt to Google Cloud Storage gs://${BUCKET_NAME}/config/target_urls.txt..."
gcloud storage cp target_urls.txt "gs://${BUCKET_NAME}/config/target_urls.txt"

echo "================================================================"
echo "🎉 TARGET LIST UPLOADED SUCCESSFULLY TO GCS!"
echo "================================================================"
echo "📂 Live Cloud Storage Location:"
echo "   gs://${BUCKET_NAME}/config/target_urls.txt"
echo ""
echo "🌐 Your customer can view and edit this list directly in GCP Web UI:"
echo "   https://console.cloud.google.com/storage/browser/${BUCKET_NAME}/config"
echo "================================================================"
