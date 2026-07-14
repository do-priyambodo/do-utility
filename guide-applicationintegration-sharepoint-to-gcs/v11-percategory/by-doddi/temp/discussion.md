# 💬 V11 Category-Based SharePoint-to-GCS Synchronization Architecture & Brainstorm (`discussion.md`)

## 1. The Context & Why We Are Evolving to V11 (`The Problem with Monoliths`)

Since July 3rd, synchronizing the entire monolithic `sites/DEN` site collection (**38,823 items across 25 nested subsites**) inside a single continuous Cloud Run execution has created multiple operational challenges:
* **High Blast Radius:** A single rate limit (`429 Too Many Requests`), temporary network glitch, or corrupted `.aspx` canvas page on one deep subsite can delay or complicate the tracking of all 38,000+ items.
* **All-or-Nothing Operational Friction:** When the AI/RAG project team (`AgentAssist`) urgently needs to refresh 50 HR policy documents, triggering a 38,000-item crawl creates unnecessary waiting, log clutter, and API bandwidth consumption.
* **Flat Data Lake Structure:** Enterprise chatbots and RAG (Retrieval-Augmented Generation) search engines perform significantly better when knowledge is cleanly partitioned by domain/category inside Google Cloud Storage (`gs://<YOUR-BUCKET>/HR/`, `gs://<YOUR-BUCKET>/Finance/`) rather than dumped into a single flat repository.

---

## 2. The Core Architectural Breakthrough: Separation of Concerns

To permanently solve this without requiring daily engineering intervention, V11 decouples **Infrastructure/Authentication** from **Business Target Scope**:

```
[ parameters.json ] (Static Infra & Auth)       [ sites-sync.json ] (Dynamic Business Scope)
 ├── GCP Project ID                              ├── Category 1: HR Policies (prefix: /hr/)
 ├── M365 Tenant / Client IDs                    ├── Category 2: Finance Q3 (prefix: /finance/)
 ├── Secret Manager Path                         └── Category 3: Legal SOPs (prefix: /legal/)
 └── Service Account Email                                    │
       │                                                      │
       └─────────────────────── T ────────────────────────────┘
                                │
                                ▼
         [ 🐳 Cloud Run Job (`yourorg-sharepoint-sync-v11`) ]
```

### 🔐 1. `parameters.json` (Static Infrastructure Profile)
* Configured **ONCE** during initial container deployment (`./deploy/deploy_cloud_run.sh`).
* Contains only fixed cloud environment variables: `CONFIG_ProjectId`, `CONFIG_Location`, `CONFIG_Service_Account`, `CONFIG_M365_Tenant_Id`, `CONFIG_M365_Client_Id`, `CONFIG_M365_Secret_Name`, and `CONFIG_SharePoint_Hostname`.
* **Zero business target paths** are hardcoded here.

### 📋 2. `sites-sync.json` (Dynamic Category Matrix)
* Maintained exclusively by the data/business integration team (`Janice` & Project Administrators).
* Can be stored locally alongside the scripts OR hosted dynamically inside a Google Cloud Storage configuration bucket (`gs://<YOUR-BUCKET>/config/sites-sync.json`).
* Adding, removing, or modifying a knowledge category requires **ZERO Docker rebuilds or Cloud Run deployments**!

---

## 3. Brainstorm: Two Structural Options for `sites-sync.json`

### Option 1: Simple Array of Subsites (`Minimal & Clean`)
Best if all categories write directly into the root of `CONFIG_GCS_Bucket` and you simply want the crawler to iterate through a curated list of department site paths instead of crawling the entire root tenant:

```json
{
  "target_sites": [
    "sites/DEN/HR",
    "sites/DEN/Finance",
    "sites/DEN/Legal",
    "sites/DEN/Operations"
  ]
}
```

* **Execution Behavior:** The Cloud Run container loads `sites-sync.json` and iterates through each subsite in the array cleanly. If one subsite fails or returns zero items, the loop logs a warning and cleanly continues to the next subsite without aborting the job.

---

### Option 2: Rich Category Matrix (`Superpower for RAG & AI Chatbot`) ⭐ Recommended
Best for enterprise AI platforms (`AgentAssist`). Each category gets its own distinct ID, target document library/folder path, and destination GCS folder prefix:

```json
{
  "categories": [
    {
      "category_id": "hr-policies",
      "display_name": "Human Resources Policies & SOPs",
      "sharepoint_site": "sites/DEN/HR",
      "sharepoint_library": "Documents/Policies_2026",
      "gcs_destination_prefix": "categories/hr/"
    },
    {
      "category_id": "finance-q3",
      "display_name": "Finance Q3 Reports & Budgets",
      "sharepoint_site": "sites/DEN/Finance",
      "sharepoint_library": "Documents/Reports",
      "gcs_destination_prefix": "categories/finance/"
    },
    {
      "category_id": "legal-contracts",
      "display_name": "Legal Standard Templates & Master Agreements",
      "sharepoint_site": "sites/DEN/Legal",
      "sharepoint_library": "all",
      "gcs_destination_prefix": "categories/legal/"
    },
    {
      "category_id": "tech-sops",
      "display_name": "Engineering Standard Operating Procedures",
      "sharepoint_site": "sites/DEN/Engineering",
      "sharepoint_library": "Documents/SOPs",
      "gcs_destination_prefix": "categories/engineering/"
    }
  ]
}
```

#### Why Option 2 Is a Superpower:
1. **Granular Knowledge Partitioning:** Every department's files land in their own isolated prefix inside GCS (`gs://<YOUR-BUCKET>/categories/hr/...`). When your Vertex AI Search or GenAI RAG indexer runs, you can scope AI knowledge searches directly to specific prefixes depending on the user's role!
2. **Deep Folder Targeting:** If the HR department has 10,000 archived 2020 files but the chatbot only needs 2026 policies, setting `"sharepoint_library": "Documents/Policies_2026"` ensures the crawler skips 90% of irrelevant legacy data.
3. **Multi-Mode Execution Flexibility:**
   * **Unattended Scheduled Loop (`All Categories`):** When the default Cloud Scheduler cron fires (`0 */6 * * *`), `main.py` loads `sites-sync.json` and runs all categories in parallel or sequential chunks.
   * **Targeted On-Demand Override (`Single Category`):** If the Legal team uploads an urgent contract template at 3:00 PM, an operator can execute a targeted 2-minute sync by passing an override parameter:
     ```bash
     gcloud run jobs execute <YOUR-JOB-NAME> --update-env-vars="TARGET_CATEGORY_ID=legal-contracts"
     ```
     Or via a dedicated Cloud Scheduler cron that sends `{"category_id": "legal-contracts"}` in its HTTP POST payload!

---

## 4. Next Steps & Action Plan for Preparation

1. **Align on Option 2 vs Option 1:** Confirm with the project team tomorrow that the **Rich Category Matrix (`Option 2`)** is the preferred schema for the AI knowledge base.
2. **Draft the Initial `sites-sync.json` Matrix:** Identify the top 3 to 5 high-priority departments or subsite paths from the `DEN` hierarchy to include in the initial V11 launch.
3. **Refine `main.py` to Support `sites-sync.json`:** Update the discovery engine so that if `sites-sync.json` exists in the container or configuration bucket, it iterates over `categories[]` and applies the specific `gcs_destination_prefix` and `sharepoint_library` overrides dynamically.
