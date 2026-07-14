# Enterprise M365 SharePoint to Google Cloud Storage (GCS) Per-Category Sharded Synchronization Pipeline (`V11.0 Per-Category Release`)

An enterprise-grade, rugged serverless synchronization pipeline built for massive scale (**38,800+ SharePoint assets across nested subsites and 23+ departments**). Decouples static cloud infrastructure (`parameters.json`) from dynamic SharePoint subsite targeting (`sites-sync.json`) using an **Option 1 Master Sequential Category Loop**.

Features **Rugged Enterprise Best Practices (`v11-percategory`)**, including:
- **Configuration Decoupling (`sites-sync.json`)**: Shards large enterprise site collections into manageable category tiers (`tier1-den-root-only`, `tier1-business`, `tier1-consumer`, `tier2-medium-departments`, etc.) targeting `"sharepoint_library": "all"`.
- **Fast Subsite Discovery (`check/discover_categories.py`)**: Resolves all child subsite categories under any root portal in **<3 seconds** without crawling libraries or counting items.
- **Master Serial Category Loop & RAM Isolation**: `main.py` iterates sequentially over each category in `sites-sync.json`, wiping local memory buffers (`all_list.clear()`, `sync_list.clear()`, `target_sites.clear()`) after every category to guarantee O(1) memory safety (<8 GB Cloud Run limit).
- **Duplicate Crawl Prevention (`include_subsites: false`)**: Root-scoped entries (`sites/DEN`) inspect only root libraries without descending into child departments (`Consumer`, `Business`).
- **Sharded Metadata & Master Aggregator (`combine_metadata_shards`)**: Each category job writes local metadata to `gs://<bucket>/<prefix>/config/metadata_part.jsonl`. At completion, `combine_metadata_shards()` atomically aggregates all shards into `gs://<bucket>/config/metadata.jsonl` for Vertex AI Search (`AgentAssist`).

---

## 🧭 Master Documentation & Operational Runbook Portal

To prevent duplication and keep instructions authoritative, all deployment, operational, and architectural procedures are maintained in dedicated topic documents. **Select your operational task below:**

### 🚀 1. Production Per-Category Sharded Synchronization (`Start Here - Recommended V11 Guide`)
👉 **Open Runbook:** [DO-SYNC-SELECTED-CATEGORY.md](DO-SYNC-SELECTED-CATEGORY.md)

Follow the comprehensive **10-Step Per-Category Operations Runbook** for end-to-end setup, authentication, prerequisites, fast category discovery, and both Option 1 Master Loop and single-category override execution:
1. **GCP & IAM Prerequisites (Steps 1–2)**: Authenticate, validate `parameters.json` and `sites-sync.json`.
2. **Discover Subsites (<3s) (Step 3)**: Execute `python3 check/discover_categories.py --root="sites/your-portal"`.
3. **Automated Master Deployment (Steps 4–7)**: Deploy Cloud Run container (`deploy_cloud_run.sh`), Application Integration workflows (`deploy_workflows.py`), and daily midnight Cloud Scheduler job (`deploy_category_scheduler.sh`).
4. **Pre-Sync Verification (Step 8)**: Run targeted Mode A (`--category=tier1-business`) or master loop Mode B (`python3 check/check_syncall_before.py`).
5. **Execute Synchronization (Step 9)**: Trigger Option 1 Master Loop (`gcloud scheduler jobs run ...`) or single-category override (`--update-env-vars="TARGET_CATEGORY_ID=..."`).
6. **Post-Sync Verification (Step 10)**: Confirm 100% GCS completeness across category shards (`check_syncall_after.py`).

---

### 🏛️ 2. Legacy Monolithic Full Site Collection Synchronization (`Single Target Traversal - DO NOT USE IN V11`)
👉 **Open Runbook:** [DO-SYNC-ALL-SHAREPOINT-DONOTUSE.md](DO-SYNC-ALL-SHAREPOINT-DONOTUSE.md)

Our classical monolithic 10-step operations guide that synchronizes an entire SharePoint site collection (`CONFIG_Sharepoint_Sites`) in a single continuous 24-hour Cloud Run traversal without per-category subsite sharding. Note: In V11, please use `DO-SYNC-SELECTED-CATEGORY.md` above instead.

---

### 🎯 3. Selective & On-Demand URL List Synchronization (`target_urls.txt`)
👉 **Open Runbook:** [DO-SYNC-TARGET-URLS.md](DO-SYNC-TARGET-URLS.md)

Dedicated playbook for bypassing folder traversal and instantly syncing or re-rendering a precise list of specific SharePoint file URLs or Modern Site Page (`.aspx`) URLs in seconds via `gs://<bucket>/config/target_urls.txt` or JSON request payloads.

---

### 🔍 4. Real-Time Progress Monitoring & Log Tracking Guide
👉 **Open Monitoring Guide:** [DO-CHECKPROGRESS.md](DO-CHECKPROGRESS.md)

Dedicated operational tracking playbook for streaming live Cloud Run container heartbeats, running instant ad-hoc GCS bucket snapshots (`du -s`), and filtering directly for rate-limiting or exception logs (`severity>=ERROR`).

---

### 🏗️ 5. Architecture & Technical Topology
👉 **Open Technical Reference:** [ARCHITECTURE.md](ARCHITECTURE.md)

Detailed system architecture diagrams (`Mermaid`), component interaction flows (Cloud Scheduler $\rightarrow$ Cloud Run $\rightarrow$ Application Integration $\rightarrow$ SharePoint / GCS), micro-batching design, and O(1) Delta Cache mathematical guarantees.

---

### 🔧 5. Troubleshooting & Operations Guide
👉 **Open Operations Guide:** [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

Comprehensive remediation playbook covering M365 authentication failures, Graph API rate throttling (`HTTP 429`), Cloud Run timeouts, and Playwright PDF rendering diagnostics.

---

## ⚙️ Configuration Files Overview

- [sites-sync.json](sites-sync.json): Dynamic 3-Tier Sharded Category Matrix and target library scopes (`sharepoint_library: all`).
- [parameters.json](parameters.json): Static GCP & M365 infrastructure credentials, Secret Manager paths, hostname, and batching limits (`CONFIG_Batch_Size`, `CONFIG_Max_Parallel_Workers`).
- [cf-sharepoint/config_schema.py](cf-sharepoint/config_schema.py): Strict schema validator ensuring static cloud keys and valid configuration rules.
