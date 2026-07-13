# Enterprise M365 SharePoint to Google Cloud Storage (GCS) Synchronization Pipeline (`V10.0 Enterprise Release`)

An enterprise-grade, rugged serverless synchronization pipeline built for scale (**14,000+ SharePoint assets across nested subsites and departments**). Synchronizes standard SharePoint Document Libraries (`Files`) and automatically converts Modern SharePoint Site Pages (`.aspx`) into high-fidelity executive `.pdf` reports (`Pages`) stored directly in Google Cloud Storage (`GCS`).

Features **Rugged Enterprise Best Practices (`awesome-agv v3.6.0`)**, including:
- **Canonical Single Source of Truth Discovery (`cf-sharepoint/sharepoint_engine`)**: Shared 4-Strategy Multi-Threaded inventory crawling and page classification used across both local diagnostic CLI tools and the Cloud Run container.
- **High-Fidelity Playwright (`headless Chromium`) Rendering**: Stage 1 mandatory conversion engine generating responsive executive `.pdf` page snapshots (`.aspx -> .pdf`).
- **O(1) Pre-Render Delta Caching**: Evaluates last-modified timestamps against `gs://bucket/config/metadata.jsonl` *before* downloading or launching browser rendering threads — skipping up-to-date items instantly (`<10ms`).
- **Fail-Fast Configuration Validation (`cf-sharepoint/config_schema.py`)**: Strict startup schema enforcement preventing silent misconfigurations.
- **High-Speed Pre/Post-Flight Verification Suite**: Multi-threaded client-side inspection scripts (`check_syncall_*.py`, `check_metadata_jsonl.py`) verifying exact subsite/department counts in seconds (`~5–15s`).

---

## 🧭 Master Documentation & Operational Runbook Portal

To prevent duplication and keep instructions authoritative, all deployment, operational, and architectural procedures are maintained in dedicated topic documents. **Select your operational task below:**

### 🚀 1. Production Full Enterprise Synchronization (`Start Here`)
👉 **Open Runbook:** [DO-SYNC-ALL-SHAREPOINT.md](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v10-10Jul2026/by-doddi/DO-SYNC-ALL-SHAREPOINT.md)

Follow the comprehensive **Complete 10-Step Operations Runbook** for end-to-end deployment and full site collection synchronization:
1. Validate & configure [`parameters.json`](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v10-10Jul2026/by-doddi/parameters.json).
2. Deploy or verify IAM Prerequisite service accounts & GCP Secret Manager M365 credentials.
3. Deploy Application Integration Parent (`Orchestrator`) and Child (`Worker`) pipelines.
4. Deploy the multi-threaded Traversal Cloud Run Service (`cf-sharepoint/main.py`) with `--timeout=3600 --cpu-boost`.
5. Verify container invoker permissions (`roles/run.invoker`).
6. Deploy automated Cloud Scheduler cron job (`CONFIG_Scheduler_Cron_Schedule`).
7. **Pre-Flight Verification**: Execute high-speed pre-sync multi-threaded discovery (`check/check_syncall_before.py`).
8. **Execute Enterprise Sync**: Trigger interactive or scheduler synchronization (`sync/sync_sharepoint_to_gcs.py`).
9. **Active Real-Time Monitoring**: Monitor live batch processing and storage progress (`Logs Explorer` / `watch gcloud storage ls`).
10. **Post-Sync Verification**: Verify 100% GCS inventory completion (`check/check_syncall_after.py`) and inspect GCS metadata catalog (`check/check_metadata_jsonl.py`).

---

### 🎯 2. Selective & Incremental Synchronization (`Scoped Workloads`)
👉 **Open Runbook:** [DO-SYNC-SELECTED-SHAREPOINT.md](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v10-10Jul2026/by-doddi/DO-SYNC-SELECTED-SHAREPOINT.md)

Dedicated playbook for scoping synchronization to a specific subsite department, specific document library, or specific URL list (`target_urls.txt`). Ideal for targeted refreshes or departmental onboarding.

---

### 🏗️ 3. Architecture & Technical Topology
👉 **Open Technical Reference:** [ARCHITECTURE.md](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v10-10Jul2026/by-doddi/ARCHITECTURE.md)

Detailed system architecture diagrams (`Mermaid`), component interaction flows (Cloud Scheduler $\rightarrow$ Cloud Run $\rightarrow$ Application Integration $\rightarrow$ SharePoint / GCS), micro-batching design, and O(1) Delta Cache mathematical guarantees.

---

### 🔧 4. Troubleshooting & Operations Guide
👉 **Open Operations Guide:** [TROUBLESHOOTING.md](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v10-10Jul2026/by-doddi/TROUBLESHOOTING.md)

Diagnostic playbooks, common OData rate-limiting solutions (`HTTP 429`), Azure AD / Entra ID OAuth token diagnostics, Cloud Run container timeout sizing (`--timeout=3600`), and GCS metadata verification errors.

---

### 🤖 5. Google Knowledge Agents (GKA) & Agent Builder Live Integration
👉 **Open GKA Guide:** [docs/GUIDE_GKA_Live_SharePoint_Links.md](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v10-10Jul2026/by-doddi/docs/GUIDE_GKA_Live_SharePoint_Links.md)

How to connect synchronized GCS files (`files/`), rendered page snapshots (`pages/`), and live SharePoint deep links (`structData.sharepoint_url`) to Google Knowledge Catalog and Vertex AI Agent Builder.

---

## 🛠️ Core Verification & Diagnostic Command Suite

Quick reference for the client-side pre-flight and post-sync CLI tools provided in `check/` and `sync/`:

| Component Script | Execution Command | Purpose |
| :--- | :--- | :--- |
| **Pre-Flight Inventory Check** | `python3 check/check_syncall_before.py` | Executes 20-thread direct discovery (~5–15s). Prints Executive Subsite Breakdown Table (`Files \| Pages \| Total`). |
| **Post-Sync Completion Check** | `python3 check/check_syncall_after.py` | Audits physical GCS bucket contents against live SharePoint inventory to verify 100% sync parity. |
| **GCS Metadata Catalog Check** | `python3 check/check_metadata_jsonl.py` | Parses `gs://<bucket>/config/metadata.jsonl` and reports exact counts of registered Document Files vs Modern Site Pages. |
| **Interactive Pipeline Trigger** | `python3 sync/sync_sharepoint_to_gcs.py` | Dynamically resolves Cloud Run service URI from parameters and triggers full enterprise synchronization. |
| **Automated Unit Test Harness** | `python3 -m unittest discover tests -v` | Executes instant offline unit tests verifying parameter validation (`config_schema.py`) and item classification logic. |

---

## 📋 Directory Organization

```
by-doddi/
├── DO-SYNC-ALL-SHAREPOINT.md         # Canonical 9-Step Full Enterprise Sync Runbook
├── DO-SYNC-SELECTED-SHAREPOINT.md    # Selective & Incremental Sync Runbook
├── ARCHITECTURE.md                   # System Architecture & Technical Specifications
├── TROUBLESHOOTING.md                # Operations & Diagnostics Guide
├── parameters.json                   # Pipeline Configuration Parameters
├── check/                            # Pre/Post-Flight Diagnostic CLI Tools
│   ├── check_syncall_before.py       # High-speed pre-sync inventory check (~5-15s)
│   ├── check_syncall_after.py        # Post-sync verification report
│   ├── check_metadata_jsonl.py       # GCS metadata catalog inspection script
│   └── check_entra_id_auth.py        # Azure AD Graph API authentication audit
├── sync/                             # Client-Side Synchronization Pipeline Triggers
├── cf-sharepoint/                    # Production Traversal Cloud Run Service (Python)
│   ├── main.py                       # Cloud Run HTTP Entry Point & Logging
│   ├── config_schema.py              # Strict Parameter Schema Validator
│   └── sharepoint_engine/            # Single Source of Truth Discovery Package
├── deploy/                           # Automated Cloud Run & Scheduler Deploy Scripts
├── tests/                            # Automated Deterministic Unit Test Harness
└── docs/                             # Additional Specialized Guides
```
