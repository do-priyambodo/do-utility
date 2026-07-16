# Session Rules & Active Workflows (`do-applicationintegration` / `do-utility`)

## Primary Working Repository & Sync Direction Mandate (`CRITICAL RULE`)
- **Primary Working Repository (Single Source of Truth for all active development, edits, testing, and debugging):**
  `/usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/`
- **Downstream Sync/Mirror Target Only (`do-utility`):**
  `/usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-utility/guide-applicationintegration-sharepoint-to-gcs/`
- **DO NOT** perform direct feature edits or start tasks inside `do-utility`. Always work strictly inside `customer-maxis/.../v10-10Jul2026` or `customer-maxis/.../v11-percategory` and sync/mirror changes downstream to `do-utility`.

## Mandatory Bidirectional Code Mirroring & Auto-Push Rule
For all modifications performed:
Whenever any file is modified, added, or deleted inside EITHER of the following active version directories (`v10-10Jul2026` or `v11-percategory`):
- **Location A (`customer-maxis` - Primary):** `/usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v10-10Jul2026` and `v11-percategory`
- **Location B (`do-utility` - Mirror Target):** `/usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-utility/guide-applicationintegration-sharepoint-to-gcs/v10-10Jul2026` and `v11-percategory`

The exact same changes MUST be mirrored/copied to the corresponding version directory in the other repository so both remain identical. Furthermore, stage, commit, and `git push` to remote GitHub on every change.

## Customer Data & Local Path Anonymization Mandate (`Strict Guardrail`)

### 1. Zero Customer Hardcoding in Code & Documentation
When writing or updating any application code (`.py`, `.sh`), markdown runbooks (`.md`), release milestone banners, or git commit/tag messages across this repository:
- **Never hardcode specific customer names** (e.g., `Maxis`, `Customer X`). Use generic terms such as `Customer Production`, `Enterprise Tenant`, or `<YOUR-ORG>`.
- **Never hardcode specific tenant IDs or GCP Project IDs** (e.g., `mxs-agentassist-dev`). Always use `<YOUR-PROJECT-ID>` or reference `config-parameters.json`.
- **Never hardcode specific GCS bucket names or resource labels** (e.g., `fullsharepoint-1stjuly`). Always use `<YOUR-GCS-BUCKET>` or dynamically query from `config-parameters.json`.

### 2. Zero Local Developer Paths in Documentation
- **Never hardcode local developer filesystem paths** (e.g., `/usr/local/google/home/username/...` or `C:\Users\...`) in markdown runbooks, `README.md`, or deployment instructions.
- Always use **relative paths** (`./deploy/deploy_cloud_run.sh`, `DO-SYNC-ALL-SHAREPOINT.md`) or generic placeholder directories (`/path/to/your/repo/v10-10Jul2026/by-yourorg`).

### 3. Separation of Concerns
All tenant-specific configuration values and customer secrets must exist exclusively inside local environment configuration files (`config-parameters.json`, `.env.local`). Code and documentation must remain 100% anonymized, generic, and suitable for sharing or public distribution at all times.
