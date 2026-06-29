# Maxis SharePoint to GCS Synchronization — Master Architecture & Scaling Plan

## Executive Summary
This document serves as the master architectural reference and future scaling plan for the Maxis SharePoint-to-GCS synchronization pipeline (V6.0). It captures all evaluated conversion methodologies, engine comparison matrices, and production scaling steps.

---

## 1. Architectural Conversion Methodologies (PDF Generation Options)

To solve customer feedback regarding missing content, unrendered images, and 1-line error files ("too complex to render") during `.aspx` export, three primary rendering architectures were evaluated:

### Methodology 1: Headless Chromium via Playwright (Recommended Production Default)
*   **Mechanism**: Spawns a complete headless Chromium browser instance inside our Option A custom Docker container (`mcr.microsoft.com/playwright/python:v1.44.0-jammy`). Loads the extracted HTML payload, waits for DOM/network stabilization (`networkidle`), and prints an exact desktop vector PDF (`page.pdf()`).
*   **Pros**: 100% pixel-perfect rendering matching modern browser layouts; handles complex CSS grid, flexbox, and dynamic client-side JS seamlessly; produces rich, executive-grade reports (~300KB–1.2MB).
*   **Cons**: Higher memory consumption (~250MB–400MB RAM per page); slower container startup (~4-5 seconds launch).

### Methodology 2: WeasyPrint HTML5 Vector Engine (Fallback Engine)
*   **Mechanism**: Utilizes the lightweight WeasyPrint HTML/CSS compilation library. Takes our universal HTML extractor output (which harvests main sections, sidebars, accordions, and inline base64 images) and compiles it directly into a clean executive PDF document.
*   **Pros**: Extremely fast container execution (<2 seconds); low memory footprint (~100MB–150MB RAM); produces clean, selectable text and vector graphics.
*   **Cons**: Does not execute client-side JavaScript (mitigated by our pre-harvesting extraction pipeline). Used as automatic fallback if container Chromium binaries are missing.

### Methodology 3: Gotenberg / External Dedicated Microservice
*   **Mechanism**: Offloads document rendering to an external Dockerized API container (Gotenberg) running Chrome/LibreOffice.
*   **Pros**: Decouples heavy rendering compute from serverless API endpoints.
*   **Cons**: Introduces unnecessary network latency, extra infrastructure costs, and operational maintenance overhead for Maxis.

---

## 2. Engine Comparison Matrix

| Feature / Criteria | Methodology 1: Playwright (Recommended Default) | Methodology 2: WeasyPrint (Fallback Engine) | Methodology 3: Gotenberg Microservice |
| :--- | :--- | :--- | :--- |
| **Configuration Value** | `"playwright"` | `"weasyprint"` | N/A (External Service) |
| **Rendering Engine** | Full Headless Chromium Browser | Lightweight HTML5 / CSS Vector Compilation | External Dockerized API |
| **Memory Consumption**| ~250MB – 400MB per page | ~100MB – 150MB per page | Low locally / High remotely |
| **Execution Speed** | Moderate (~4-5s per page) | Fast (<2s per page) | Network dependent |
| **Maintenance** | Option A Custom Docker Container | Zero external infrastructure | Requires dedicated VM/Cluster |

---

## 3. Enterprise Production Readiness & Scaling Roadmap (3,000+ Pages)

### Phase 1: Enterprise Scaling & Rate-Limit Mitigation
*   **O(1) GCS Delta Cache (`$delta`)**: The pipeline automatically checks existing files in `gs://doddi-bucket-sharepoint-sync/pages/`. Pages matching existing timestamps are skipped instantly, protecting Microsoft Graph API limits and ensuring daily incremental runs finish in under 60 seconds.
*   **Parallel Micro-Batching**: Inventory is sliced into micro-batches (`CONFIG_Batch_Size: 10`) running concurrently across 10 parallel workers (`CONFIG_Max_Parallel_Workers: 10`).
*   **Action Item**: Execute an off-peak **Initial Seed Warm-Up** run to populate the delta cache across all 3,000+ items.

### Phase 2: Downstream Contact Center AI Ingestion (GKA & Vertex AI Search)
*   **Automated Citation Routing**: Every sync appends exact citations to `metadata.jsonl`:
    ```json
    {"id": "gs://doddi-bucket-sharepoint-sync/pages/Culture.pdf", "structData": {"sharepoint_url": "https://maxis.sharepoint.com/.../Culture.aspx"}}
    ```
*   **Action Item**: Configure Genesys Agent Assist widget with `linkMetadataKey: "sharepoint_url"` so agent clicks navigate directly to authenticated live SharePoint pages instead of storage blobs.

### Phase 3: Operational Monitoring & Lifecycle Management
*   **Action Item**: Configure Cloud Logging alerts for `HTTP 500` or container crashes on `doddi-sharepoint-list-files`.
*   **Action Item**: Apply a 90-day GCS lifecycle deletion rule on `gs://doddi-bucket-sharepoint-sync/config/status/` audit records.
