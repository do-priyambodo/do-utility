# 🗺️ V11 Category-Based SharePoint-to-GCS Synchronization Implementation Plan (`plan.md`)

## 1. Goal Description & Executive Summary

The V11 Category-Based Synchronization architecture (`v11-percategory`) transitions enterprise SharePoint ingestion from a monolithic all-at-once model (`sites/DEN` crawling **38,823 items across 59 document libraries and 23 subsites** in a single 20-minute discovery loop) to a modular, fault-isolated, **Category-Driven Ingestion Pipeline**.

### The 4 Core Pillars of V11:
1. **Decoupled Architecture (`Separation of Concerns`):** `parameters.json` becomes your static infrastructure profile (`Project ID`, `Service Account`, `Tenant ID`, `Secret Path`). A new **`sites-sync.json`** file acts as the dynamic, hot-swappable category matrix. Adding or changing categories requires **zero Docker rebuilds or container deployments**.
2. **3-Tier Department Sharding:** Based on the customer's steep Pareto inventory distribution (`sample-sites.txt`), we shard the 23 subsites into Mega-Categories (`Business` 9.5k, `Consumer` 8.2k, `Hotlink` 5.2k, `System-Procedure` 4.3k, `DEN Root` 4k) and Lightweight Batches, running on staggered schedules to eliminate Microsoft Graph API rate throttling (`429`).
3. **Duplicate Crawl Prevention (`include_subsites: false`):** We update `cf-sharepoint/main.py` with an `include_subsites` check around `get_all_subsites_recursive()`, allowing root subsites (`sites/DEN`) to sync only their direct root items without recursively crawling child departments (`Consumer`, `Business`), guaranteeing **zero duplicate objects**.
4. **Vertex AI Unified Master Metadata Engine (`combine_metadata_shards`):** To satisfy Vertex AI Search's requirement for a single master `metadata.jsonl` catalog while eliminating concurrent write race conditions, each category job writes its own sharded `metadata_part.jsonl`. At the end of any job run, an atomic helper merges all shards into `gs://<bucket>/config/metadata.jsonl` while preserving 100% of both `source_url` (GCS text) and `sharepoint_url` (M365 chatbot citation links).

---

## 2. User Review Required & Design Guardrails

> [!IMPORTANT]
> **Zero Docker Rebuild Guarantee**  
> Once `v11-percategory` is deployed to Cloud Run (`yourorg-sharepoint-sync-v11`), business operators only edit or upload `sites-sync.json`. No `./deploy/deploy_cloud_run.sh` calls are ever needed when onboarding new departments.

> [!WARNING]
> **Strict Anonymization & Bidirectional Mirroring Mandate**  
> 1. **No Customer Hardcoding:** All code (`.py`, `.sh`) and documentation (`.md`) MUST use generic variables (`<YOUR-PROJECT-ID>`, `<YOUR-GCS-BUCKET>`, `sites/<YOUR-SITE>/<CATEGORY>`).
> 2. **1-to-1 Repository Mirroring:** Every file created or modified in `customer-maxis/.../v11-percategory` will be mirrored automatically to `do-utility/.../v11-percategory` and pushed to GitHub on every turn.

---

## 3. Proposed Changes & Implementation Roadmap

Group files by component and order logically. Separate components with horizontal rules for visual clarity.

### [Component 1: Dynamic Category Configuration & Schema]
Decouple `parameters.json` and introduce `sites-sync.json` with the 3-Tier Sharding Matrix.

#### [NEW] `config/sites-sync.json`
```json
{
  "categories": [
    {
      "category_id": "tier1-den-root-only",
      "display_name": "DEN Root Portal Documents & Guides ONLY",
      "sharepoint_site": "sites/DEN",
      "include_subsites": false,
      "sharepoint_library": "Documents",
      "gcs_destination_prefix": "categories/den-root/",
      "cron_schedule": "0 0 * * *"
    },
    {
      "category_id": "tier1-business",
      "display_name": "Business Department Policies & Documents",
      "sharepoint_site": "sites/DEN/Business",
      "include_subsites": true,
      "sharepoint_library": "Documents",
      "gcs_destination_prefix": "categories/business/",
      "cron_schedule": "0 2 * * *"
    },
    {
      "category_id": "tier1-consumer",
      "display_name": "Consumer Department SOPs & Guides",
      "sharepoint_site": "sites/DEN/Consumer",
      "include_subsites": true,
      "sharepoint_library": "Documents",
      "gcs_destination_prefix": "categories/consumer/",
      "cron_schedule": "0 4 * * *"
    },
    {
      "category_id": "tier1-hotlink",
      "display_name": "Hotlink Department Documents",
      "sharepoint_site": "sites/DEN/Hotlink",
      "include_subsites": true,
      "sharepoint_library": "Documents",
      "gcs_destination_prefix": "categories/hotlink/",
      "cron_schedule": "0 6 * * *"
    },
    {
      "category_id": "tier1-system-procedure",
      "display_name": "System & Procedure Standard Guidelines",
      "sharepoint_site": "sites/DEN/System-Procedure",
      "include_subsites": true,
      "sharepoint_library": "Documents",
      "gcs_destination_prefix": "categories/system-procedure/",
      "cron_schedule": "0 8 * * *"
    },
    {
      "category_id": "tier2-medium-departments",
      "display_name": "Channels, Enterprise Solutions & QA",
      "sharepoint_site": [
        "sites/DEN/Channels",
        "sites/DEN/Enterprise-Solutions",
        "sites/DEN/ChannelMarketing",
        "sites/DEN/Quality-Assurance"
      ],
      "include_subsites": true,
      "sharepoint_library": "Documents",
      "gcs_destination_prefix": "categories/medium-departments/",
      "cron_schedule": "0 10 * * *"
    },
    {
      "category_id": "tier3-specialized-teams",
      "display_name": "MEPS, Credit, BCP, FAQ & Specialized Teams",
      "sharepoint_site": [
        "sites/DEN/MEPS",
        "sites/DEN/Credit-Operations",
        "sites/DEN/BCP",
        "sites/DEN/FAQ",
        "sites/DEN/Assisted",
        "sites/DEN/CDPU",
        "sites/DEN/Customer-Support",
        "sites/DEN/Customer_First",
        "sites/DEN/DistributionMgmt",
        "sites/DEN/Quicklinks",
        "sites/DEN/Self_Serve",
        "sites/DEN/Service-Insights",
        "sites/DEN/Training"
      ],
      "include_subsites": true,
      "sharepoint_library": "Documents",
      "gcs_destination_prefix": "categories/specialized-teams/",
      "cron_schedule": "0 12 * * *"
    }
  ]
}
```

---

### [Component 2: SharePoint Crawler Engine (`Duplicate Prevention & Sharded Metadata`)]
Modify the discovery logic inside `cf-sharepoint/main.py` to support `include_subsites`, dynamic `sites-sync.json` routing, and atomic master metadata aggregation.

#### [MODIFY] `cf-sharepoint/main.py`
1. **Duplicate Prevention (`include_subsites: false` Check):**
   ```python
   # Check if the active category configuration requests non-recursive / root-only discovery
   include_subsites = req_data.get("include_subsites", params.get("CONFIG_Include_Subsites", True))

   if not include_subsites:
       print(f"🎯 Non-Recursive / Exact Target Mode Active ('include_subsites': False)")
       print(f"   Inspecting only root site '{CONFIG_Sharepoint_Sites}' without crawling child departments.")
       root_site_obj = resolve_site_info(CONFIG_Sharepoint_Sites, headers)
       target_sites_to_scan = [root_site_obj] if root_site_obj else []
   else:
       print(f"🏢 Recursive Discovery Mode Active ('include_subsites': True)")
       target_sites_to_scan = get_all_subsites_recursive(CONFIG_Sharepoint_Sites, headers)
   ```

2. **Sharded Category Metadata Output:**
   Direct every category job to write its local metadata strictly to its category shard:
   ```python
   category_prefix = req_data.get("gcs_destination_prefix", params.get("CONFIG_GCS_Prefix", ""))
   local_shard_path = f"gs://{CONFIG_GCS_Bucket}/{category_prefix.rstrip('/')}/config/metadata_part.jsonl" if category_prefix else f"gs://{CONFIG_GCS_Bucket}/config/metadata_part.jsonl"
   # Write metadata shard with 100% preservation of id, structData.sharepoint_url, and structData.source_url
   upload_to_gcs_atomic(local_shard_path, metadata_lines_buffer)
   ```

3. **Atomic Master Aggregator (`combine_metadata_shards`):**
   Execute at the end of `main.py` when any category run completes:
   ```python
   def combine_metadata_shards(bucket_name):
       print(f"⚡ Master Metadata Aggregator: Combining all category shards into root config/metadata.jsonl...")
       storage_client = storage.Client()
       bucket = storage_client.bucket(bucket_name)
       blobs = list(bucket.list_blobs(prefix="categories/"))
       
       master_catalog = {}
       for blob in blobs:
           if blob.name.endswith("metadata_part.jsonl"):
               content = blob.download_as_text()
               for line in content.strip().splitlines():
                   if not line.strip(): continue
                   try:
                       entry = json.loads(line)
                       entry_id = entry.get("id") or entry.get("structData", {}).get("source_url")
                       if entry_id:
                           master_catalog[entry_id] = line
                   except Exception:
                       pass
                       
       master_blob = bucket.blob("config/metadata.jsonl")
       master_blob.upload_from_string("\n".join(master_catalog.values()) + "\n", content_type="application/jsonl")
       print(f"✅ Master Catalog Updated! Total unified records for Vertex AI Search: {len(master_catalog)}")
   ```

---

### [Component 3: Verification & Runbook Hygiene]
Ensure all operational scripts support Category-Based dispatching.

#### [NEW] `deploy/deploy_category_scheduler.sh`
Helper script to deploy or update individual category cron jobs pointing to the universal Cloud Run container URL with `--message-body='{"category_id": "tier1-business"}'`.

#### [NEW] `DO-SYNC-SELECTED-CATEGORY.md`
Standardized copy-pasteable runbook for category execution, monitoring, and verification.

---

## 4. Verification Plan

### Automated Tests
1. **Validate Parameter & Matrix Syntax:**
   ```bash
   python3 util/validate_params.py --config=config/sites-sync.json
   ```
2. **Execute Discovery Unit & Regression Tests:**
   ```bash
   python3 -m unittest discover tests -v
   ```

### Manual Verification
1. **Pre-Flight Category Audit (`check_syncall_before.py --category=tier1-business`):**
   Verify that Microsoft Graph API resolves only `sites/DEN/Business` and finishes discovery in **<15 seconds** with zero duplicate counts from `Consumer`.
2. **Pre-Flight Root Audit (`check_syncall_before.py --category=tier1-den-root-only`):**
   Verify that with `"include_subsites": false`, the root check finds exactly the 4,076 root items without crawling down into the 23 child departments.
3. **Master Metadata Verification:**
   Trigger two different category runs and verify via `gcloud storage cat gs://<YOUR-BUCKET>/config/metadata.jsonl | wc -l` that the unified master file contains the merged records from both categories with both `source_url` and `sharepoint_url` intact.
