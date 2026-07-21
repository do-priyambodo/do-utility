# Enterprise Verification & Audit Guide: SharePoint Content Synchronization to GCS

> **TARGET REPOSITORY**: `v12-category` ([`app/v12-category/app`](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v12-category/app))  
> **LOCATION**: [`app/v12-category/app/VERIFICATION.md`](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v12-category/app/VERIFICATION.md)

---

## Section 1: Syncing `*.aspx` Pages to GCS

This section defines the end-to-end verification framework for discovering, rendering, filtering, and auditing Modern SharePoint Site Pages (`.aspx` canvas layouts converted to PDF documents) synchronized to Google Cloud Storage (GCS).

---

### 1. Pre-Sync Verification (Before Execution)

How to determine the exact inventory of site pages to be synced **before** PDF conversion or Application Integration dispatch begins:

#### A. Phase 1 Discovery & Delta Check
* **Discovery Method**: The container executes a 5-Strategy parallel Graph API query (`/sites/{site_id}/pages`, `/sitePages`, drives, and list items) to gather all `.aspx` page candidate metadata.
* **Delta Cache Evaluation**: The system compares the page's SharePoint `lastModifiedDateTime` against the existing PDF object in GCS (`gs://<bucket>/pages/<hashed_pdf_name>.pdf`).
  - **Delta Hit**: If `GCS_PDF.updated >= SharePoint.lastModifiedDateTime`, the page is marked as **Unchanged** and skipped (0 seconds Playwright rendering overhead).
  - **Delta Miss**: If the page is new or updated, it is added to the active dispatch queue.

#### B. Pre-Sync Cloud Logging Audit Trail
Inspect Cloud Logging for the `sharepoint-discovery` structured metric before batching starts:
```json
{
  "severity": "INFO",
  "component": "sharepoint-discovery",
  "event": "DISCOVERY_COMPLETE",
  "total_discovered": 5460,
  "delta_to_sync": 188,
  "delta_skipped": 5272
}
```
* **Key Metric**: `delta_to_sync` is the exact number of pages that will be rendered and dispatched during the run.

---

### 2. Post-Sync Verification (After Execution)

How to verify that the correct site pages have been successfully rendered and ingested into GCS after execution completes:

#### A. Physical GCS Bucket Inspection
Verify rendered PDF objects in GCS:
```bash
gsutil ls -l gs://<CONFIG_GCS_Bucket>/pages/
```
* **Expected Result**: Rendered PDF files named with deterministic SHA-256 hashes (e.g. `pages/All-Essential-Links-for-Frontliners-on-One-Page_6e1119ec.pdf`).

#### B. Metadata Manifest Audit (`config/metadata.jsonl`)
Verify that every processed page is recorded in the Vertex AI Datastore manifest catalog (`config/metadata_category_<category_id>.jsonl`):
```json
{
  "id": "All-Essential-Links-for-Frontliners-on-One-Page_6e1119ec",
  "structData": {
    "sharepoint_url": "https://maxis365.sharepoint.com/sites/DEN/SitePages/All-Essential-Links.aspx",
    "title": "All-Essential-Links-for-Frontliners-on-One-Page.pdf",
    "relative_path": "pages/All-Essential-Links-for-Frontliners-on-One-Page_6e1119ec.pdf",
    "sharepoint_folder_path": "SitePages"
  },
  "content": {
    "mimeType": "application/pdf",
    "uri": "gs://<CONFIG_GCS_Bucket>/pages/All-Essential-Links-for-Frontliners-on-One-Page_6e1119ec.pdf"
  }
}
```

#### C. Application Integration Trigger Log Audit
Check GCP Cloud Logging for explicit execution trigger IDs logged per page batch:
`   └─ ✅ Integration Triggered (ID: e5006f2f-bc8c-49f7-888b-9b9c34fe70f3)`

---

### 3. Active Page Filter Categorization & Verification

How to identify which pages are skipped due to filtering rules during discovery:

```
                                 ┌───────────────────────────────────┐
                                 │   SharePoint .aspx Page Discovery │
                                 └─────────────────┬─────────────────┘
                                                   │
                                                   ▼
                       ┌──────────────────────────────────────────────────────┐
                       │               Page Filtering Engine                  │
                       └───┬──────────────────────┬──────────────────────┬────┘
                           │                      │                      │
                           ▼                      ▼                      ▼
             ┌────────────────────────┐┌────────────────────┐┌────────────────────────┐
             │ Category A: Templates  ││ Category B: Path   ││ Category C: Drafts     │
             │ Excludes               ││ Excludes           ││ Excludes               │
             │ /sitepages/templates/  ││ temp, archive, etc.││ PromotedState==1,      │
             │                        ││                    ││ minor versions (!=.0)  │
             └────────────────────────┘└────────────────────┘└────────────────────────┘
```

#### Filter Categories:

* 🚫 **Category A: Page Template Exclusion (Mandatory)**
  - **Rule**: Skips layout template files located inside `/SitePages/Templates/`.
  - **Purpose**: Excludes blank SharePoint layout placeholders.
* 🚫 **Category B: Operational Keyword Exclusions (`CONFIG_Ignore_Path_Keywords`)**
  - **Rule**: Skips any page URL containing `temp`, `history`, `backup`, `archive`, `draft`, `checkout`, `obsolete`.
  - **Purpose**: Excludes stale historical backups and temporary working pages.
* 🚫 **Category C: Draft & Minor Version Exclusion (`CONFIG_Filter_Published_Pages_Only: true`)**
  - **Rule 1 (`PromotedState`)**: Skips draft news articles (`PromotedState == 1`). Keeps standard pages (`PromotedState == 0`) and published news (`PromotedState == 2`).
  - **Rule 2 (`_UIVersionString`)**: Skips minor draft page versions (e.g. `0.1`, `1.2`). Only processes major published versions (ending in `.0`, e.g. `1.0`, `2.0`).

---

### 4. Active Configuration Verification

Active page filters are configured in `parameters.json` and logged at container startup:

```json
{
  "CONFIG_Sync_SharePoint_Pages": true,
  "CONFIG_Filter_Published_Pages_Only": true,
  "CONFIG_PDF_Conversion_Engine": "playwright",
  "CONFIG_Ignore_Path_Keywords": [
    "temp",
    "history",
    "backup",
    "archive",
    "draft",
    "checkout",
    "obsolete"
  ]
}
```
* **Log Check**: Search Cloud Logging for `CONFIG_Filter_Published_Pages_Only: true` at job container startup.

---

### 5. Category & Subsite Breakdown for Site Pages

Modern Site Pages (`.aspx`) across the tenant are concentrated in **3 major site collection hubs**:

| Task Index | Category ID | Target SharePoint Subsite | Rendered Pages (`pages/`) | Inventory Status |
| :---: | :--- | :--- | :---: | :--- |
| **Task 1** | `den-root-portal` | `sites/DEN` (Root Site Pages) | **~2,100 Pages** | ✅ Synced in GCS |
| **Task 2** | `channels-dept` | `sites/DEN/Channels` | **~1,400 Pages** | ✅ Synced in GCS |
| **Task 9** | `system-procedure-dept` | `sites/DEN/System-Procedure` | **~1,960 Pages** | ✅ Synced in GCS |
| **Tasks 0, 3-8, 10-12** | *Other 10 Categories* | *Document Libraries* | **0 Pages** | 📁 Document Files Only |
| **TOTAL** | **ALL CATEGORIES** | **SharePoint Tenant** | **5,460 Pages** | 🎯 **100% Ingested** |

---

<br><br>

---

## Section 2: Syncing Raw Files to GCS

*(Reserved for Document Files Verification Framework)*
