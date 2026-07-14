# 📋 V11 Category-Based Synchronization Implementation Checklist (`tasks.md`)

This checklist tracks our step-by-step engineering progression across the V11 Per-Category SharePoint-to-GCS Synchronization pipeline. Every task must be completed and mirrored across both repositories (`customer-maxis` and `do-utility`) with strict anonymization.

---

### Phase 1: Configuration Decoupling (`sites-sync.json` & `parameters.json`)
- [ ] **Task 1.1:** Create `config/sites-sync.json` with top-level `"root_portal_site"` (`sites/DEN`) and 3-Tier Sharding Matrix (`tier1-den-root-only`, `tier1-business`, `tier1-consumer`, `tier1-hotlink`, `tier1-system-procedure`, `tier2-medium-departments`, `tier3-specialized-teams`), standardizing on `"sharepoint_library": "all"`.
- [ ] **Task 1.2:** Clean up `parameters.json` by removing target scopes (`CONFIG_Sharepoint_Sites` and `CONFIG_Sharepoint_Library`), preserving only cloud infrastructure variables, Secret Manager path, and `CONFIG_SharePoint_Hostname`.
- [ ] **Task 1.3:** Create/update configuration loader logic (`util/config_loader.py` or helper in `main.py`) to seamlessly read both `parameters.json` and `sites-sync.json` (from local disk or GCS bucket).
- [ ] **Task 1.4:** Run JSON validation (`python3 -m json.tool config/sites-sync.json`) and confirm clean syntax across both repositories.

---

### Phase 2: Diagnostic & Fast Discovery Engine (`check/` utilities)
- [ ] **Task 2.1:** Create `check/discover_categories.py` — 2-second fast discovery tool that connects via Graph API (`GET /v1.0/sites/{id}/subsites`), reads `root_portal_site` from `sites-sync.json` (or `--root=...`), and outputs all child departments without counting items.
- [ ] **Task 2.2:** Update `check/check_syncall_before.py` to load `sites-sync.json` and support both **Mode A** (`--category=tier1-business` targeted 15s audit) and **Mode B** (Sequential category-by-category loop with RAM wiping and summary table).
- [ ] **Task 2.3:** Update `check/check_syncall_after.py` to mirror the exact same Option 1 serial loop and single-category override logic, verifying that all files/pages landed in their exact `gcs_destination_prefix` shards.
- [ ] **Task 2.4:** Run Python syntax check (`python3 -m py_compile check/*.py`) across both repositories.

---

### Phase 3: Core Synchronization Engine & Vertex AI Master Aggregator (`cf-sharepoint/main.py`)
- [ ] **Task 3.1:** Update `cf-sharepoint/main.py` entry point to execute Option 1 Master Category Loop across `categories[]` from `sites-sync.json`, plus supporting optional single-category on-demand overrides via `--update-env-vars="TARGET_CATEGORY_ID=..."`.
- [ ] **Task 3.2:** Implement Duplicate Crawl Prevention (`include_subsites: false`) inside `main.py`: wrapping `get_all_subsites_recursive()` so root collections (`sites/DEN`) scan only root libraries without descending into child departments (`Consumer`, `Business`).
- [ ] **Task 3.3:** Implement Sharded Metadata Output inside `main.py`: directing every category to write its local metadata strictly to its shard (`gs://<bucket>/<prefix>/config/metadata_part.jsonl`) preserving 100% of `source_url` and `sharepoint_url`.
- [ ] **Task 3.4:** Implement `combine_metadata_shards(bucket_name)` at the very end of `main.py`: atomically aggregating all category shards into `gs://<bucket>/config/metadata.jsonl` for Vertex AI Search (`AgentAssist`), followed by RAM reclamation (`target_sites_to_scan.clear()`).
- [ ] **Task 3.5:** Run Python syntax check and unit/regression tests (`python3 -m py_compile cf-sharepoint/main.py && python3 -m unittest discover tests -v`) across both repositories.

---

### Phase 4: Deployment Automation & Operator Runbooks (`deploy/` & documentation)
- [ ] **Task 4.1:** Update `deploy/deploy_cloud_run.sh` to deploy the V11 container without hardcoded SharePoint site variables, setting `CONFIG_SITES_SYNC_PATH=config/sites-sync.json`.
- [ ] **Task 4.2:** Create `deploy/deploy_category_scheduler.sh` helper to deploy and check the single Option 1 daily Cloud Scheduler job (`yourorg-sharepoint-sync-daily`).
- [ ] **Task 4.3:** Create `DO-SYNC-SELECTED-CATEGORY.md` comprehensive operator runbook detailing `discover_categories.py`, Option 1 master loop, single-category overrides (`--update-env-vars`), and diagnostic verification.
- [ ] **Task 4.4:** Perform final git status audit across both `customer-maxis` and `do-utility` repositories, guaranteeing 100% 1-to-1 mirroring and pushing all commits to `origin main`.
