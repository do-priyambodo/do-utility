# 🎯 V11 Operator Runbook: Selective & On-Demand URL List Synchronization (`DO-SYNC-TARGET-URLS.md`)

This runbook guides operators and developers on how to use the **Selective URL List Synchronization (`target_urls`)** feature of the V11 pipeline (`v11-percategory`). 

Instead of traversing entire site collections or subsite libraries, this mechanism allows you to bypass directory crawling entirely and instantly synchronize or re-render a precise list of specific SharePoint file URLs or Modern Site Page (`.aspx`) URLs in seconds.

---

## 1. How Selective URL Synchronization Works

When the Cloud Run Job (`yourorg-sharepoint-list-files`) executes, it checks if `target_urls` are specified (either via the API payload or from a live GCS configuration file `gs://<bucket>/config/target_urls.txt`). 

If `target_urls` are detected:
1. **Traverse Bypass**: The crawler skips full folder traversal across document libraries (`drives`), saving API calls and reducing execution time from minutes to seconds (`<15s`).
2. **Direct Processing**: The pipeline inspects only the exact URLs provided in the list.
3. **Delta Cache Check & Inactive Cleanup**: 
   - If a target URL is unchanged in SharePoint compared to GCS, it is skipped via O(1) Delta Cache.
   - If a target URL has been deleted or is inactive in SharePoint, the pipeline automatically detects and deletes the stale `.pdf` or document from GCS (`gs://<bucket>/...`).

---

## 2. Option A: Dynamic GCS Config File (`target_urls.txt`) — Recommended

The easiest way to trigger selective synchronization without modifying code or passing large API payloads is via a text file stored in your GCS bucket: `gs://<bucket>/config/target_urls.txt`.

### Step 1: Create `target_urls.txt` locally or directly in GCS
Create a simple text file (`target_urls.txt`) listing one SharePoint asset URL per line. You can include comments starting with `#`:

```text
# ==============================================================================
# V11 TARGET URLS CONFIGURATION FILE (`gs://your-bucket/config/target_urls.txt`)
# Add exact SharePoint URLs below (one per line) for direct targeted sync:
# ==============================================================================

https://yourorg.sharepoint.com/sites/DEN/SitePages/Emergency-SOP.aspx
https://yourorg.sharepoint.com/sites/DEN/Business/Shared%20Documents/Policies/Security-Policy-2026.docx
https://yourorg.sharepoint.com/sites/DEN/Consumer/Shared%20Documents/Guides/Quickstart.pdf
```

### Step 2: Upload to your GCS Bucket
Upload the file to the `config/` directory inside your destination bucket:

```bash
gcloud storage cp target_urls.txt gs://yourorg-bucket-sharepoint-sync/config/target_urls.txt
```

### Step 3: Trigger the Cloud Run Job with `check_gcs_config=true`
Run the Cloud Run Job and instruct it to read the live `config/target_urls.txt` manifest:

```bash
gcloud run jobs execute yourorg-sharepoint-list-files \
  --region=asia-southeast1 \
  --update-env-vars="TARGET_CATEGORY_ID=tier1-business" \
  --args="--check-gcs-config=true"
```
*(Or pass `{"check_gcs_config": true}` via HTTP POST if triggering via Cloud Functions or Application Integration API).*

---

## 3. Option B: Direct HTTP Payload (`target_urls` Array)

If you are invoking the pipeline programmatically via Cloud Functions, Application Integration, or REST POST requests, you can pass the URL list directly inside the JSON request payload:

```bash
curl -X POST "https://asia-southeast1-yourorg.cloudfunctions.net/yourorg-sharepoint-list-files" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "check_gcs_config": false,
    "force_full_sync": true,
    "target_urls": [
      "https://yourorg.sharepoint.com/sites/DEN/SitePages/Executive-Briefing.aspx",
      "https://yourorg.sharepoint.com/sites/DEN/MEPS/Shared%20Documents/Architecture-V11.docx"
    ]
  }'
```

---

## 4. Automatic Path Sharding & Storage Mapping

When `target_urls` are processed, the pipeline automatically maps the URL to the exact GCS storage path matching your category or library structure:
- **Site Pages (`.aspx`)**: Rendered via headless Chromium and saved to `pages/<subfolder>/<filename>.pdf`.
- **Document Files (`.docx`, `.pdf`, `.xlsx`)**: Saved to `files/<subfolder>/<filename>.<ext>`.

If the asset belongs to a sharded category prefix (e.g. `categories/business/`), the file safely lands inside that exact category shard: `gs://<bucket>/categories/business/pages/Executive-Briefing.pdf`.

---

## 5. Verification & Observability

To verify that your selective target URLs were successfully processed and uploaded:
1. **Check Cloud Run Logs Explorer**:
   Look for the structured JSON metric confirming target URL processing:
   ```json
   {
     "severity": "INFO",
     "component": "sharepoint-discovery",
     "event": "DISCOVERY_COMPLETE",
     "total_discovered": 2,
     "delta_to_sync": 2
   }
   ```
2. **Inspect GCS Destination directly**:
   ```bash
   gcloud storage ls gs://yourorg-bucket-sharepoint-sync/pages/
   ```
