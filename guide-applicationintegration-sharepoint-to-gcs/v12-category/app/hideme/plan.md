# 🛠️ Maxis V12-Category Production Remediation & Execution Plan

> **STATUS**: ACTIVE
> **LAST UPDATED**: July 21, 2026
> **TARGET REPOSITORY**: `v12-category` ([`app/v12-category/app`](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v12-category/app))

---

## 🎯 ACTIVE REMEDIATION PLAN: Maxis Production Environment Fixes

This active plan addresses the root causes of file sync discrepancies, manifest record gaps, and subsite 404 resolution failures identified during the customer's July 20, 2026 test run.

---

### 📍 Phase 1: Fix Primary Key (`doc_id`) Collision Bug in Manifest Code
* **Target Files**: 
  - [`app/v12-category/app/cf-sharepoint/main.py`](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v12-category/app/cf-sharepoint/main.py)
  - [`app/v12-category/app/main.py`](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v12-category/app/main.py)
* **Root Cause**:
  `main.py` currently extracts `base_name` from `item.get("Name")` (the unhashed raw filename, e.g. `Glossary.pptx`), instead of `item.get("RelativePath")` (which already has the 8-character SHA hash assigned during discovery, e.g. `Glossary_8f7b2a11.pptx`). Files in different subfolders sharing identical titles overwrite each other in `config/metadata.jsonl`, causing 905 dispatched items to disappear from the Vertex AI Search index.
* **Proposed Code Modification**:
  Change `base_name` extraction to use `item.get("RelativePath")`:
  ```python
  # Derive doc_id from RelativePath to reuse the existing 8-char SHA hash
  rel_path = item.get("RelativePath", "")
  base_filename = rel_path.rsplit('/', 1)[-1].rsplit('.', 1)[0] if rel_path else item.get("Name", "doc").rsplit('.', 1)[0]
  doc_id = re.sub(r'[^a-zA-Z0-9_-]', '_', base_filename)
  ```
* **Expected Result**: 100% unique primary keys (`doc_id`) in `metadata.jsonl` matching the exact GCS object names (e.g. `Glossary_8f7b2a11`), eliminating the 905-item manifest discrepancy.

---

### 📍 Phase 2: Automatic Subsite 404 Resolution in Code (Preserve `parameters.json`)
* **Target Files**: 
  - [`app/v12-category/app/cf-sharepoint/main.py`](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v12-category/app/cf-sharepoint/main.py)
  - [`app/v12-category/app/main.py`](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v12-category/app/main.py)
* **Directive**:
  - `parameters.json` will **NOT** be modified. Maxis's original parameter definitions will be preserved 100%.
* **Code Mechanism**:
  - When Graph API returns HTTP 404 `itemNotFound` for subsite paths configured in `parameters.json` (e.g. `sites/DEN/Enterprise-Solutions`), the Python code automatically falls back to resolving `sites/DEN` and filters by sub-folder name.
* **Expected Result**: 100% of all files and pages discovered without modifying `parameters.json`.

---

### 📍 Phase 3: Enable Combined Files & Pages Sync (`files=true`, `pages=true`)
* **Target File**: 
  - [`app/v12-category/app/hideme/maxis-parameters.json`](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/logs-from-maxis-troubleshoot/20260720-V12category-1300PM/maxis-parameters.json)
* **Action Steps**:
  1. Set `"CONFIG_Sync_SharePoint_Files": true` and `"CONFIG_Sync_SharePoint_Pages": true`.
* **Expected Behavior**:
  All **5,460 Modern Site Pages** previously rendered into `gs://fullsharepoint-1stjuly-v12category/pages/` will hit the O(1) GCS Delta Cache check and skip rendering instantly (0 seconds overhead), while allowing 100% container bandwidth to focus on syncing document files and outputting a complete combined manifest for Vertex AI Search.

---

<br><br>

---

## 📦 INACTIVE / COMPLETED ARCHIVE: Original V12 Sharding Plan

<details>
<summary><b>Click to expand archived initial V12 design plan</b></summary>

### 1. Core Architectural Pillars (Option 2 - Simple Sharding)
* **Inline Shard Definitions**: Category definitions defined under `"CONFIG_Categories"` in `parameters.json`.
* **Sequential Execution (`--parallelism=1`)**: Tasks run sequentially bound to `CLOUD_RUN_TASK_INDEX`.
* **Flat Hashed GCS Layout**: Objects saved under `files/` and `pages/` with 8-char SHA suffixes.
* **Human-Readable Search Shield**: Clean titles and paths preserved in `structData`.

</details>
