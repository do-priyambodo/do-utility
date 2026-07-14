# 🗺️ V11 Category-Based SharePoint-to-GCS Synchronization Implementation Plan (`plan.md`)

## 1. Goal Description & Executive Summary

The V11 Category-Based Synchronization architecture (`v11-percategory`) transitions enterprise SharePoint ingestion from a monolithic all-at-once model (`sites/DEN` crawling **38,823 items across 59 document libraries and 23 subsites** in a single 20-minute discovery loop) to a modular, fault-isolated, **Category-Driven Ingestion Pipeline**.

### The 4 Core Pillars of V11:
1. **Decoupled Architecture (`Separation of Concerns`):** `parameters.json` becomes your static infrastructure profile (`Project ID`, `Service Account`, `Tenant ID`, `Secret Path`). A new **`sites-sync.json`** file acts as the dynamic, hot-swappable category matrix. Adding or changing categories requires **zero Docker rebuilds or container deployments**.
2. **Option 1 Single Master Scheduler Loop (`Sequential Sharding`):** Per user alignment (`Option 1 is better`), we deploy exactly **ONE** Cloud Scheduler cron job in GCP (`yourorg-sharepoint-sync-daily`). When triggered, `main.py` loads `sites-sync.json` and iterates cleanly through the 6 category groups one by one. Zero scheduler management clutter for the customer!
3. **Duplicate Crawl Prevention (`include_subsites: false`):** We update `cf-sharepoint/main.py` with an `include_subsites` check around `get_all_subsites_recursive()`, allowing root subsites (`sites/DEN`) to sync only their direct root items without recursively crawling child departments (`Consumer`, `Business`), guaranteeing **zero duplicate objects across the 38,823 inventory**.
4. **Vertex AI Unified Master Metadata Engine (`combine_metadata_shards`):** To satisfy Vertex AI Search's requirement for a single master `metadata.jsonl` catalog while eliminating concurrent write race conditions, each category job writes its own sharded `metadata_part.jsonl`. At the end of the master category loop, an atomic helper merges all shards into `gs://<bucket>/config/metadata.jsonl` while preserving 100% of both `source_url` (GCS text) and `sharepoint_url` (M365 chatbot citation links).

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

### [Component 1: Dynamic Category Configuration & Schema (`Option 1 Clean Loop + Root Portal Header`)]
Decouple `parameters.json` and introduce `sites-sync.json` with the top-level `"root_portal_site"` property and 3-Tier Sharding Matrix.

#### [NEW] `config/sites-sync.json`
```json
{
  "root_portal_site": "sites/DEN",
  "categories": [
    {
      "category_id": "tier1-den-root-only",
      "display_name": "DEN Root Portal Documents & Guides ONLY",
      "sharepoint_site": "sites/DEN",
      "include_subsites": false,
      "sharepoint_library": "all",
      "gcs_destination_prefix": "categories/den-root/"
    },
    {
      "category_id": "tier1-business",
      "display_name": "Business Department Policies & Documents",
      "sharepoint_site": "sites/DEN/Business",
      "include_subsites": true,
      "sharepoint_library": "all",
      "gcs_destination_prefix": "categories/business/"
    },
    {
      "category_id": "tier1-consumer",
      "display_name": "Consumer Department SOPs & Guides",
      "sharepoint_site": "sites/DEN/Consumer",
      "include_subsites": true,
      "sharepoint_library": "all",
      "gcs_destination_prefix": "categories/consumer/"
    },
    {
      "category_id": "tier1-hotlink",
      "display_name": "Hotlink Department Documents",
      "sharepoint_site": "sites/DEN/Hotlink",
      "include_subsites": true,
      "sharepoint_library": "all",
      "gcs_destination_prefix": "categories/hotlink/"
    },
    {
      "category_id": "tier1-system-procedure",
      "display_name": "System & Procedure Standard Guidelines",
      "sharepoint_site": "sites/DEN/System-Procedure",
      "include_subsites": true,
      "sharepoint_library": "all",
      "gcs_destination_prefix": "categories/system-procedure/"
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
      "sharepoint_library": "all",
      "gcs_destination_prefix": "categories/medium-departments/"
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
      "sharepoint_library": "all",
      "gcs_destination_prefix": "categories/specialized-teams/"
    }
  ]
}
```

---

### [Component 2: SharePoint Crawler Engine (`Master Loop, Duplicate Prevention & Sharded Metadata`)]
Modify the discovery logic inside `cf-sharepoint/main.py` to support `Option 1 Master Loop`, `include_subsites`, dynamic `sites-sync.json` routing, and atomic master metadata aggregation.

#### [MODIFY] `cf-sharepoint/main.py`
1. **Option 1 Master Category Loop & Optional On-Demand Overrides:**
   ```python
   # Load category matrix from sites-sync.json
   sites_sync_config = load_sites_sync_config(params)
   categories_to_sync = sites_sync_config.get("categories", [])
   
   # Check if an operator requested a single-category on-demand override
   target_override = os.environ.get("TARGET_CATEGORY_ID") or req_data.get("category_id")
   if target_override:
       categories_to_sync = [c for c in categories_to_sync if c.get("category_id") == target_override]
       print(f"🎯 On-Demand Single Category Override Active: Running ONLY '{target_override}'")
   else:
       print(f"🔄 Option 1 Master Loop Active: Iterating through {len(categories_to_sync)} category groups sequentially.")
       
   for category in categories_to_sync:
       process_category_sync(category, params, headers)
       # Clear inventory from memory and close session before proceeding to next category
       clear_category_memory_buffer()
   ```

2. **Duplicate Prevention (`include_subsites: false` Check):**
   ```python
   # Inside process_category_sync(): Check if active category requests non-recursive / root-only discovery
   include_subsites = category.get("include_subsites", True)

   if not include_subsites:
       print(f"🎯 Non-Recursive / Exact Target Mode Active ('include_subsites': False)")
       print(f"   Inspecting only root site '{category['sharepoint_site']}' without crawling child departments.")
       root_site_obj = resolve_site_info(category["sharepoint_site"], headers)
       target_sites_to_scan = [root_site_obj] if root_site_obj else []
   else:
       print(f"🏢 Recursive Discovery Mode Active ('include_subsites': True)")
       target_sites_to_scan = get_all_subsites_recursive(category["sharepoint_site"], headers)
   ```

3. **Sharded Category Metadata Output:**
   Direct every category job to write its local metadata strictly to its category shard:
   ```python
   category_prefix = category.get("gcs_destination_prefix", "")
   local_shard_path = f"gs://{CONFIG_GCS_Bucket}/{category_prefix.rstrip('/')}/config/metadata_part.jsonl" if category_prefix else f"gs://{CONFIG_GCS_Bucket}/config/metadata_part.jsonl"
   # Write metadata shard with 100% preservation of id, structData.sharepoint_url, and structData.source_url
   upload_to_gcs_atomic(local_shard_path, metadata_lines_buffer)
   ```

4. **Atomic Master Aggregator (`combine_metadata_shards`):**
   Execute at the very end of `main.py` after the master loop completes all categories:
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

### [Component 3: Verification & Runbook Hygiene (`discover_categories`, `check_syncall_before/after`)]
Ensure all operational scripts and diagnostic checks support Category-Based dispatching, fast discovery, and serial memory isolation.

#### [NEW] `check/discover_categories.py`
Lightweight 2-second utility that opens `sites-sync.json`, reads `"root_portal_site": "sites/DEN"` (or accepts `--root=sites/DEN`), connects via Graph API (`/v1.0/sites/{root_id}/subsites`), and lists every child department without counting files/pages.

#### [MODIFY] `check/check_syncall_before.py` & `check/check_syncall_after.py`
Update both verification scripts to load `sites-sync.json` and support two execution modes:
* **Mode A (Targeted Single Category Audit):** `python3 check/check_syncall_before.py --category=tier1-business` $\rightarrow$ Audits ONLY the Business subsite and its GCS prefix in <15 seconds.
* **Mode B (Master Serial Category-by-Category Loop):** `python3 check/check_syncall_before.py` $\rightarrow$ Loops through each category in `sites-sync.json` sequentially, clearing memory after each category, and prints a unified summary table across all 38,823 items.

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
1. **Fast Category Discovery (`discover_categories.py`):**
   Run `python3 check/discover_categories.py` and verify it prints all 23 child departments inside **<3 seconds** without counting files.
2. **Pre-Flight Category Audit (`check_syncall_before.py --category=tier1-business`):**
   Verify that Microsoft Graph API resolves only `sites/DEN/Business` and finishes discovery in **<15 seconds** with zero duplicate counts from `Consumer`.
3. **Pre-Flight Root Audit (`check_syncall_before.py --category=tier1-den-root-only`):**
   Verify that with `"include_subsites": false`, the root check finds exactly the 4,076 root items without crawling down into the 23 child departments.
4. **Master Metadata Verification:**
   Run the master loop and verify via `gcloud storage cat gs://<YOUR-BUCKET>/config/metadata.jsonl | wc -l` that the unified master file contains the merged records from all categories with both `source_url` and `sharepoint_url` intact.
