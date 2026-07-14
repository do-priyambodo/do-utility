# 📘 V11 Operator Runbook: Per-Category SharePoint-to-GCS Synchronization (`DO-SYNC-SELECTED-CATEGORY.md`)

This runbook guides operators, system administrators, and DevOps engineers on how to inspect, verify, deploy, and execute the **V11 Category-Based Synchronization Pipeline (`v11-percategory`)**.

---

## 1. Architecture Overview

The V11 pipeline decouples static cloud infrastructure (`parameters.json`) from dynamic SharePoint subsite targeting (`config/sites-sync.json`). It operates under the **Option 1 Master Sequential Loop** architecture:
1. **Single Master Cloud Run Job (`yourorg-sharepoint-list-files`)**: Iterates sequentially over the `categories[]` array inside `sites-sync.json`.
2. **Serial Memory Isolation**: After syncing each category, the crawler wipes its local RAM buffer (`all_list.clear()`, `sync_list.clear()`, `target_sites.clear()`), guaranteeing O(1) memory safety (<8 GB Cloud Run limit) across 38,823+ enterprise assets.
3. **Duplicate Crawl Prevention**: Root categories (`tier1-den-root-only`) use `"include_subsites": false` to inspect ONLY root libraries (`sites/DEN`), preventing redundant crawling into child departments (`sites/DEN/Consumer`).
4. **Sharded Metadata & Master Aggregator**: Each category writes its local metadata to `gs://<bucket>/<prefix>/config/metadata_part.jsonl`. At job completion, `combine_metadata_shards()` atomically aggregates all shards into a unified `gs://<bucket>/config/metadata.jsonl` manifest for Vertex AI Search (`AgentAssist`).

---

## 2. Fast Subsite Discovery (`discover_categories.py`)

If you want to discover all available child subsites/departments under your root portal site in **<3 seconds** (without waiting 30 minutes for library counting), execute:

```bash
python3 check/discover_categories.py
```

### Sample Output:
```
================================================================================
🚀 V11 SHAREPOINT FAST CATEGORY DISCOVERY (ROOT ONLY — NO ITEM COUNTING)
================================================================================
 • Hostname        : yourorg.sharepoint.com
 • Root Site Scope : sites/DEN
🔐 Authenticating with Microsoft Entra ID...
🌐 Resolving Root Site ID via Microsoft Graph API...
✅ Root Site Resolved! ID: a1b2c3...
⚡ Discovering direct child subsites (categories)...

--------------------------------------------------------------------------------
Found 23 Subsite Categories under 'sites/DEN' (Execution Time: 2.14s):
--------------------------------------------------------------------------------
No.  Category / Subsite Name            Web URL                                 
--------------------------------------------------------------------------------
1    Business                           https://yourorg.sharepoint.com/sites/DEN/Business
2    Consumer                           https://yourorg.sharepoint.com/sites/DEN/Consumer
3    Hotlink                            https://yourorg.sharepoint.com/sites/DEN/Hotlink
...
```

To test a custom root path, pass `--root="sites/ANOTHER_PORTAL"`:
```bash
python3 check/discover_categories.py --root="sites/ANOTHER_PORTAL"
```

---

## 3. Pre-Sync Diagnostic Audit (`check_syncall_before.py`)

Before triggering synchronization, verify how many items are currently in SharePoint versus how many are already cached in GCS.

### Mode A (Targeted Single Category Audit — <15 seconds):
To inspect only one specific category (e.g. `tier1-business`):
```bash
python3 check/check_syncall_before.py --category=tier1-business
```

### Mode B (Master Sequential Category Loop Audit):
To inspect every category inside `sites-sync.json` sequentially with RAM isolation:
```bash
python3 check/check_syncall_before.py
```

---

## 4. Execution Modes (Full vs. Single Category)

### Mode 1: Daily Automated Master Loop (All Categories)
The Cloud Scheduler job (`yourorg-sharepoint-list-files-daily-master`) automatically triggers the Cloud Run Job at midnight (`0 0 * * *`). To trigger the full master loop manually:
```bash
gcloud run jobs execute yourorg-sharepoint-list-files --region=asia-southeast1
```

### Mode 2: On-Demand Single-Category Override
If a specific department (e.g. `tier1-business`) needs immediate emergency synchronization without running all other categories, pass `TARGET_CATEGORY_ID` via `--update-env-vars`:

```bash
gcloud run jobs execute yourorg-sharepoint-list-files \
  --region=asia-southeast1 \
  --update-env-vars="TARGET_CATEGORY_ID=tier1-business"
```

> **IMPORTANT**: When the single-category sync completes, remember to reset the environment variable before the next nightly run:
> ```bash
> gcloud run jobs update yourorg-sharepoint-list-files \
>   --region=asia-southeast1 \
>   --remove-env-vars="TARGET_CATEGORY_ID"
> ```

### Mode 3: Selective URL List Bypass (`target_urls.txt`)
If you need to bypass folder traversal entirely and instantly sync only a specific list of URL files or `.aspx` pages in `<15 seconds`, see the dedicated operator runbook:
👉 **[DO-SYNC-TARGET-URLS.md](DO-SYNC-TARGET-URLS.md)**

---

## 5. Post-Sync Verification (`check_syncall_after.py`)

After a sync job finishes, confirm that 100% of SharePoint target items are present in their exact GCS sharded prefixes (`gs://<bucket>/categories/<department>/...`):

```bash
# Verify all categories sequentially
python3 check/check_syncall_after.py

# Or verify a specific single category
python3 check/check_syncall_after.py --category=tier1-business
```

---

## 6. Deployment Commands

To deploy or update the V11 Cloud Run container and Cloud Scheduler job from scratch:

```bash
# 1. Deploy the 24-hour Cloud Run Job container with V11 config
bash deploy/deploy_cloud_run.sh

# 2. Configure the daily midnight Cloud Scheduler job
bash deploy/deploy_category_scheduler.sh
```
