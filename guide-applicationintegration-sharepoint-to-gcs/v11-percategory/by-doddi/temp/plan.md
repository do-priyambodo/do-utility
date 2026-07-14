# 🗺️ V11 Category-Based SharePoint-to-GCS Synchronization Implementation Plan (`plan.md`)

## 1. Goal Description & Executive Summary

The V11 Category-Based Synchronization architecture (`v11-percategory`) transitions enterprise SharePoint ingestion from a monolithic, high-blast-radius model (`sites/DEN` crawling 38,000+ items inside a single job) to a modular, fault-isolated, **Category-Driven Ingestion Pipeline**.

### Why We Are Moving to V11 Per-Category:
1. **Fault Isolation & Blast-Radius Reduction:** If one department (`Legal` or `HR`) has restricted permissions, rate limits (`429`), or broken `.aspx` canvas structures, it will never delay or impact the synchronization of other departments (`Finance`, `Engineering`, `Marketing`).
2. **Targeted GenAI / RAG Search (`AgentAssist`):** Enterprise chatbots perform significantly better when documents are cleanly partitioned by domain/category inside Google Cloud Storage (`gs://<YOUR-BUCKET>/HR/`, `gs://<YOUR-BUCKET>/Finance/`) rather than dumped into a single flat bucket.
3. **Staggered & Parallel Scheduling:** Instead of running a multi-hour crawl at midnight, categories can run on independent, lightweight 10-to-15 minute Cloud Scheduler schedules throughout the day without overwhelming Microsoft Graph API.

---

## 2. Open Questions & Architectural Options for User Selection

We have engineered three distinct operational models for V11. Please review the options below and let us know which approach aligns best with your team's workflow:

> [!TIP]
> **(Recommended) Option A: Single Cloud Run Container with Dynamic Scheduler Overrides**  
> **How it works:** We deploy exactly **ONE** universal Cloud Run Job (`yourorg-sharepoint-sync-v11`). Instead of hardcoding the site in the container, each **Cloud Scheduler Job** passes its specific category (`site_name: "DEN/HR"`, `bucket_name: "bucket-hr"`) inside its HTTP POST `message-body` payload when waking up the container!  
> **Pros:** Only ONE container to deploy and maintain! You can create 5, 10, or 20 different category cron jobs from the command line in seconds without rebuilding Docker images.

> [!IMPORTANT]
> **Option B: Multi-Profile Configuration Files (`parameters.{category}.json`)**  
> **How it works:** We maintain dedicated parameter files for each category inside a `config/` directory:
> * `config/parameters.hr.json` $\rightarrow$ (`CONFIG_Sharepoint_Sites: "sites/DEN/HR"`, `CONFIG_GCS_Bucket: "bucket-hr"`)
> * `config/parameters.finance.json` $\rightarrow$ (`CONFIG_Sharepoint_Sites: "sites/DEN/Finance"`, `CONFIG_GCS_Bucket: "bucket-finance"`)  
> **Pros:** 100% explicit local files for every department. Easy to audit and check into version control. We provide a helper wrapper `./sync_category.sh --category=hr` that hot-swaps the config and executes.

> [!NOTE]
> **Option C: Granular Folder & Document Library Partitioning**  
> **How it works:** If a department stores multiple distinct knowledge domains inside the same subsite (e.g. `sites/DEN/Operations` has `/Documents/2025_SOPs` and `/Documents/Archive`), V11 allows setting `CONFIG_Sharepoint_Library: "Documents/2025_SOPs"` so a category can target a specific high-value subfolder.

---

## 3. User Review Required & Design Guardrails

> [!WARNING]
> **Strict Anonymization & Bidirectional Mirroring Mandate**  
> As we prepare scripts and documentation inside `v11-percategory`:
> 1. **No Customer Hardcoding:** All code (`.py`, `.sh`) and documentation (`.md`) MUST use generic variables (`<YOUR-PROJECT-ID>`, `<YOUR-GCS-BUCKET>`, `sites/<YOUR-SITE>/<CATEGORY>`).
> 2. **1-to-1 Repository Mirroring:** Every file created or modified in `customer-maxis/.../v11-percategory` will be mirrored automatically to `do-utility/.../v11-percategory` and pushed to GitHub.

---

## 4. Proposed Changes & Implementation Roadmap

Separate components with horizontal rules for visual clarity.

### [Phase 1: Category Configuration Engine & Profiles]
Create standardized category configuration templates and schema validation helpers.

#### [NEW] `config/parameters.category-template.json`
```json
{
  "CONFIG_ProjectId": "<YOUR-PROJECT-ID>",
  "CONFIG_Location": "asia-southeast1",
  "CONFIG_Service_Account": "sa-sharepoint-gcs@<YOUR-PROJECT-ID>.iam.gserviceaccount.com",
  "CONFIG_Child_Integration_Name": "sharepoint-gcs-child-v11",
  "CONFIG_Parent_Integration_Name": "sharepoint-gcs-parent-v11",
  "CONFIG_SharePoint_Connection": "projects/$CONFIG_ProjectId/locations/$CONFIG_Location/connections/connection-sharepoint-sync",
  "CONFIG_Sharepoint_Sites": "sites/<YOUR-ROOT-SITE>/<CATEGORY-NAME>",
  "CONFIG_Sharepoint_Library": "Documents",
  "CONFIG_GCS_Connection": "projects/$CONFIG_ProjectId/locations/$CONFIG_Location/connections/connection-gcs-sync",
  "CONFIG_GCS_Bucket": "<YOUR-GCS-BUCKET>-<CATEGORY-NAME>",
  "CONFIG_CloudFunction_Name": "sharepoint-sync-<CATEGORY-NAME>",
  "CONFIG_M365_Tenant_Id": "<YOUR-TENANT-ID>",
  "CONFIG_M365_Client_Id": "<YOUR-CLIENT-ID>",
  "CONFIG_M365_Secret_Name": "projects/<YOUR-PROJECT-ID>/secrets/sharepoint-credentials/versions/1",
  "CONFIG_SharePoint_Hostname": "<YOUR-ORG>.sharepoint.com",
  "CONFIG_Scheduler_Job_Name": "sharepoint-cron-<CATEGORY-NAME>",
  "CONFIG_Batch_Size": 5,
  "CONFIG_Max_Parallel_Workers": 5,
  "CONFIG_Sync_SharePoint_Files": true,
  "CONFIG_Sync_SharePoint_Pages": true,
  "CONFIG_Scheduler_Cron_Schedule": "0 */6 * * *",
  "CONFIG_Developer_Group_Or_User": "user:<YOUR-EMAIL>",
  "CONFIG_PDF_Conversion_Engine": "playwright"
}
```

---

### [Phase 2: Modular Category Deployment & Execution Scripts]
Create streamlined CLI helpers that allow deploying and executing category jobs on demand.

#### [NEW] `deploy/deploy_category_scheduler.sh`
A shell script that accepts `--category=<NAME>` or `--config=<PATH>`, reads the specific category parameters, and deploys a targeted Cloud Scheduler job pointing to either a dedicated Cloud Run Job or passing category runtime variables to a shared Cloud Run Job.

#### [NEW] `DO-SYNC-SELECTED-CATEGORY.md`
A comprehensive, copy-pasteable runbook explaining how to configure, deploy, and verify individual categories or staggered department schedules.

---

## 5. Verification Plan

### Automated Tests
1. **Validate Category Parameters Syntax:**
   ```bash
   python3 util/validate_params.py --config=config/parameters.hr.json
   ```
2. **Execute Unit Tests against Discovery Engine:**
   ```bash
   python3 -m unittest discover tests -v
   ```

### Manual Verification
1. **Pre-Flight Category Audit (`Dry-Run`):**
   Run `python3 check/check_syncall_before.py --config=config/parameters.hr.json` to verify that Microsoft Graph API resolves only the `HR` category subsite and counts its exact inventory in under 5 seconds.
2. **On-Demand Category Execution:**
   Execute the category job (`gcloud run jobs execute sharepoint-sync-hr` or via `sync_category.sh`) and verify via `gcloud storage ls gs://<YOUR-BUCKET>-hr/** | wc -l` that only target category assets land in the destination GCS bucket.
