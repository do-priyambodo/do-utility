# 🎯 Version 10 (`v10-10Jul2026`) Targeted Selected-URL SharePoint Synchronization Guide (`DO-SYNC-SELECTED-SHAREPOINT.md`)

This concise copy-paste guide walks you through synchronizing **specific selected SharePoint files or modern `.aspx` site pages** defined in your dynamic remote whitelist (`gs://bucket/config/target_urls.txt`).

---

## Step 1: Prepare & Upload Your Target URLs List (`target_urls.txt`)

Create a text file containing the exact SharePoint document URLs or Modern Site Page `.aspx` URLs you want to synchronize (one URL per line) and upload it to Google Cloud Storage:

```bash
# 1. Navigate to Version 10 working directory
cd /usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v10-10Jul2026/by-doddi

# 2. Upload or update target_urls.txt to your GCS configuration bucket
gsutil cp target_urls.txt gs://doddi-bucket-sharepoint-sync/config/target_urls.txt
```

---

## Step 2: Read-Only Dry-Run Verification (`Check Selected URLs`)

Simulate the selected synchronization without downloading files or rendering PDFs to verify that every URL in `target_urls.txt` resolves cleanly against Microsoft Graph API:

```bash
python3 check/check_sync_gcs_dynamic.py --dry-run
```

---

## Step 3: Execute Targeted Selected Synchronization

Initiate the synchronization for your selected URLs using either Option A (Terminal Python Runner) or Option B (Cloud Scheduler Targeted Job):

### Option A: Run Directly via Python Dynamic Orchestrator
```bash
python3 sync/sync_gcs_dynamic.py --force
```

### Option B: Trigger Existing Cloud Scheduler Targeted Job
```bash
gcloud scheduler jobs run doddi-sharepoint-sync-targeted \
  --location=asia-southeast1 \
  --project=work-mylab-machinelearning
```

---

## Step 4: Post-Sync Verification

Verify that your targeted files and rendered high-fidelity Playwright PDFs have landed in GCS:

```bash
# List synced objects inside the bucket
gsutil ls -la gs://doddi-bucket-sharepoint-sync/files/
gsutil ls -la gs://doddi-bucket-sharepoint-sync/pages/
```
