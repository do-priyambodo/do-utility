# Enterprise M365 SharePoint to Google Cloud Storage (GCS) Per-Category Sharded Synchronization Pipeline (`V11.0 Per-Category Release`)

An enterprise-grade, rugged serverless synchronization pipeline built for massive scale (**38,800+ SharePoint assets across nested subsites and 23+ departments**). Decouples static cloud infrastructure (`parameters.json`) from dynamic SharePoint subsite targeting (`config/sites-sync.json`) using an **Option 1 Master Sequential Category Loop**.

Features **Rugged Enterprise Best Practices (`v11-percategory`)**, including:
- **Configuration Decoupling (`config/sites-sync.json`)**: Shards large enterprise site collections into manageable category tiers (`tier1-den-root-only`, `tier1-business`, `tier1-consumer`, `tier2-medium-departments`, etc.) targeting `"sharepoint_library": "all"`.
- **Fast Subsite Discovery (`check/discover_categories.py`)**: Resolves all child subsite categories under any root portal in **<3 seconds** without crawling libraries or counting items.
- **Master Serial Category Loop & RAM Isolation**: `main.py` iterates sequentially over each category in `sites-sync.json`, wiping local memory buffers (`all_list.clear()`, `sync_list.clear()`, `target_sites.clear()`) after every category to guarantee O(1) memory safety (<8 GB Cloud Run limit).
- **Duplicate Crawl Prevention (`include_subsites: false`)**: Root-scoped entries (`sites/DEN`) inspect only root libraries without descending into child departments (`Consumer`, `Business`).
- **Sharded Metadata & Master Aggregator (`combine_metadata_shards`)**: Each category job writes local metadata to `gs://<bucket>/<prefix>/config/metadata_part.jsonl`. At completion, `combine_metadata_shards()` atomically aggregates all shards into `gs://<bucket>/config/metadata.jsonl` for Vertex AI Search (`AgentAssist`).

---

## 🧭 Master Documentation & Operational Runbook Portal

To prevent duplication and keep instructions authoritative, all deployment, operational, and architectural procedures are maintained in dedicated topic documents. **Select your operational task below:**

### 🚀 1. Production Per-Category Synchronization & Operator Runbook (`Start Here`)
👉 **Open Runbook:** [DO-SYNC-SELECTED-CATEGORY.md](DO-SYNC-SELECTED-CATEGORY.md)

Follow the comprehensive **Per-Category Operations Runbook** for end-to-end deployment, fast category discovery, and both Option 1 Master Loop and single-category override execution:
1. **Discover Subsites (<3s)**: Execute `python3 check/discover_categories.py --root="sites/your-portal"`.
2. **Configure Targets**: Edit `config/sites-sync.json` with your desired categories and GCS destination prefixes.
3. **Pre-Sync Verification**: Run targeted Mode A (`--category=tier1-business`) or master loop Mode B (`python3 check/check_syncall_before.py`).
4. **Automated Master Deployment**: Deploy Cloud Run container (`bash deploy/deploy_cloud_run.sh`) and daily midnight Cloud Scheduler job (`bash deploy/deploy_category_scheduler.sh`).
5. **On-Demand Single-Category Override**: Execute emergency department sync via `gcloud run jobs execute yourorg-sharepoint-list-files --region=asia-southeast1 --update-env-vars="TARGET_CATEGORY_ID=tier1-business"`.
6. **Post-Sync Verification**: Confirm 100% GCS completeness across category shards (`python3 check/check_syncall_after.py`).

---

### 🎯 2. Selective & On-Demand URL List Synchronization (`target_urls.txt`)
👉 **Open Runbook:** [DO-SYNC-TARGET-URLS.md](DO-SYNC-TARGET-URLS.md)

Dedicated playbook for bypassing folder traversal and instantly syncing or re-rendering a precise list of specific SharePoint file URLs or Modern Site Page (`.aspx`) URLs in seconds via `gs://<bucket>/config/target_urls.txt` or JSON request payloads.

---

### 🏗️ 3. Architecture & Technical Topology
👉 **Open Technical Reference:** [ARCHITECTURE.md](ARCHITECTURE.md)

Detailed system architecture diagrams (`Mermaid`), component interaction flows (Cloud Scheduler $\rightarrow$ Cloud Run $\rightarrow$ Application Integration $\rightarrow$ SharePoint / GCS), micro-batching design, and O(1) Delta Cache mathematical guarantees.

---

### 🔧 3. Troubleshooting & Operations Guide
👉 **Open Operations Guide:** [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

Comprehensive remediation playbook covering M365 authentication failures, Graph API rate throttling (`HTTP 429`), Cloud Run timeouts, and Playwright PDF rendering diagnostics.

---

## ⚙️ Configuration Files Overview

- [config/sites-sync.json](config/sites-sync.json): Dynamic 3-Tier Sharded Category Matrix and target library scopes (`sharepoint_library: all`).
- [parameters.json](parameters.json): Static GCP & M365 infrastructure credentials, Secret Manager paths, hostname, and batching limits (`CONFIG_Batch_Size`, `CONFIG_Max_Parallel_Workers`).
- [cf-sharepoint/config_schema.py](cf-sharepoint/config_schema.py): Strict schema validator ensuring static cloud keys and valid configuration rules.
