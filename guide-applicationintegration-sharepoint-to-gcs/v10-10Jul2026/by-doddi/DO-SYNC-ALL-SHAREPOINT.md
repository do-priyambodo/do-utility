# 🚀 Version 10 (`v10-10Jul2026`) Complete SharePoint Synchronization Guide (`DO-SYNC-ALL-SHAREPOINT.md`)

This concise step-by-step operational guide provides **copy-paste ready commands** to verify your hardware limits, perform diagnostic checks, initiate an enterprise synchronization (100,000+ SharePoint assets), and verify ingested Google Cloud Storage (GCS) inventory.

---

## Step 1: Pre-Flight Hardware Sizing & Timeout Check (`8 GiB / 4 vCPUs / 900s`)

Verify and configure the Cloud Run service (`doddi-sharepoint-list-files`) with **8 GiB memory (`8192Mi`)**, **4 vCPUs**, and a **15-minute (`900s`) timeout** to ensure Playwright Chromium renders heavy executive `.aspx` site pages with maximum multi-threaded performance:

```bash
# 1. Check current Cloud Run memory & timeout limits
gcloud run services describe doddi-sharepoint-list-files \
  --region=asia-southeast1 \
  --format="table(spec.template.spec.containers[0].resources.limits.memory, spec.template.spec.timeoutSeconds)"

# 2. Apply Enterprise Hardware Sizing (8 GiB RAM / 4 vCPUs / 900s Timeout)
gcloud run services update doddi-sharepoint-list-files \
  --region=asia-southeast1 \
  --memory=8192Mi \
  --cpu=4 \
  --timeout=900
```

---

## Step 2: Read-Only Pre-Flight Verification (`Dry-Run`)

Before triggering actual file downloads, execute our **read-only diagnostic checks** to verify Microsoft Entra ID authentication and simulate SharePoint folder discovery (completes in ~3 to 5 seconds):

```bash
# 1. Navigate to Version 10 working directory
cd /usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v10-10Jul2026/by-doddi

# 2. Verify Microsoft Entra ID / Graph API Authentication
python3 check/check_entra_id_auth.py

# 3. Simulate Full SharePoint Traversal (Dry-Run without downloading files)
python3 check/check_sync_sharepoint_to_gcs.py --dry-run
```

---

## Step 3: Execute Enterprise SharePoint-to-GCS Synchronization

Initiate the synchronization using either Option A (Terminal Python Runner) or Option B (Cloud Scheduler Job):

### Option A: Run Directly via Python Orchestrator (Recommended for Console Tracking)
Runs the complete synchronization with real-time progress logging (`100 files/batch` for standard documents, `5 pages/batch` for `.aspx` PDF rendering, and keep-alive connection pooling):

```bash
python3 sync/sync_sharepoint_to_gcs.py
```

### Option B: Trigger Existing Cloud Scheduler Job
Manually trigger your configured Cloud Scheduler cron job (`doddi-sharepoint-sync-hourly`):

```bash
gcloud scheduler jobs run doddi-sharepoint-sync-hourly \
  --location=asia-southeast1 \
  --project=work-mylab-machinelearning
```

> [!NOTE]
> **Expected First-File Timeline**:
> * **1st File visible in GCS (`gs://bucket/files/...`)**: **~3 to 5 seconds**
> * **First 100 Files (Batch #1 scheduled & streaming)**: **~8 to 12 seconds**
> * **Time Guard Safety Circuit Breaker**: Runs up to **800 seconds (`13.3 minutes`)**, cleanly saving progress and exiting with `200 OK` before any Cloud Run timeout.

---

## Step 4: Post-Sync Inventory Verification

Verify that all SharePoint files and rendered executive PDF reports have been successfully ingested into your GCS bucket:

```bash
# 1. Compare total GCS inventory against live SharePoint counts
python3 check/check_syncall_after.py

# 2. Verify generated GCS metadata catalog
gsutil ls -lh gs://doddi-bucket-sharepoint-sync/config/metadata.jsonl
```
