# Enterprise SharePoint-to-GCS Synchronization & Agent Assist Architecture

This architectural blueprint describes the end-to-end serverless synchronization pipeline, dynamic rendering engine, multi-stage Application Integration flow, and contact center AI integration (Genesys to SharePoint) for enterprise deployments.

---

## 1. Traversal Cloud Run Service (Core Engine Mechanism)

The Traversal Cloud Run service (`yourorg-sharepoint-list-files`) is the intelligence hub of the pipeline. Built with a clean modular architecture (`graph_client.py`, `sharepoint_traversal.py`, `pdf_renderer.py`, `main.py`), it combines Microsoft Graph API crawl capabilities with full browser automation.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                       TRAVERSAL CLOUD RUN SERVICE                                           │
│                                                                                                             │
│  ┌─────────────────────────┐     ┌───────────────────────────────────────────────────────────────────────┐  │
│  │   1. M365 Authentication│     │                     2. Traversal & Discovery Engine                   │  │
│  │     (graph_client.py)   │────▶│                                                                       │  │
│  │ • OAuth2 Token Cache    │     │ • Graph API Site/Drive Crawl   • Target URLs (target_urls.txt)        │  │
│  │ • Exponential Backoff   │     │ • Document Libraries Inventory • Modern Site Pages (.aspx) Harvest    │  │
│  └─────────────────────────┘     └───────────────────────────────────┬───────────────────────────────────┘  │
│                                                                      │                                      │
│                                                                      ▼                                      │
│  ┌───────────────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                             3. O(1) GCS Delta Cache & Orphan Pruning                                  │  │
│  │                                                                                                       │  │
│  │ • Compare lastModifiedDateTime against existing GCS object metadata ($delta cache)                    │  │
│  │ • INSTANT SKIP for unchanged inventory (<60s incremental execution)                                   │  │
│  │ • Automated Cleanup: Purges deleted/inactive SharePoint files from GCS                                │  │
│  └───────────────────────────────────────────────────┬───────────────────────────────────────────────────┘  │
│                                                      │                                                      │
│                                                      ▼                                                      │
│  ┌───────────────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                            4. High-Fidelity PDF Rendering Engine                                      │  │
│  │                                      (pdf_renderer.py)                                                │  │
│  │                                                                                                       │  │
│  │   ┌─────────────────────────────────────────────────┐   ┌─────────────────────────────────────────┐   │  │
│  │   │     Primary Engine: Playwright Chromium         │   │      Fallback Engine: WeasyPrint        │   │  │
│  │   │                                                 │   │                                         │   │  │
│  │   │ • Full Headless Chromium Automation             │   │ • Lightweight HTML5/CSS Compile         │   │  │
│  │   │ • Executes JS, Accordions & Dynamic Layouts     │   │ • Low Memory Footprint (~100-150MB)     │   │  │
│  │   │ • Intelligent Image URL Resolver (OData/Thumbs) │   │ • Automatic fallback if binaries absent │   │  │
│  │   └─────────────────────────────────────────────────┘   └─────────────────────────────────────────┘   │  │
│  └───────────────────────────────────────────────────┬───────────────────────────────────────────────────┘  │
│                                                      │                                                      │
│                                                      ▼                                                      │
│  ┌───────────────────────────────────────────────────────────────────────────────────────────────────────┐  │
│  │               5. Streaming Parallel Pipelined Chunk Execution & Micro-Batching                        │  │
│  │                          (CONFIG_Batch_Size × CONFIG_Max_Parallel_Workers)                            │  │
│  │                                                                                                       │  │
│  │ • Pre-Render Delta Cache Filter: Skips unchanged pages instantly before any browser rendering         │  │
│  │ • Processes items in chunks (e.g. 5x5=25) with parallel Playwright rendering across thread pool       │  │
│  │ • Immediately dispatches micro-batches per chunk & flushes RAM for continuous incremental progress    │  │
│  └───────────────────────────────────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Detailed Component Breakdown

1. **Authentication & Resiliency (`graph_client.py`)**:
   * Authenticates against Microsoft Entra ID (M365 Tenant) using OAuth2 client credentials (`CONFIG_M365_Client_Id` + GCP Secret Manager secret).
   * Implements robust retry policies with exponential backoff and token caching to handle transient throttling (`429 Too Many Requests`).

2. **Recursive Traversal & Layout Harvesting (`sharepoint_traversal.py`)**:
   * **Full Site Crawl**: Recursively traverses Microsoft Graph API endpoints (`/sites/{site-id}/drives`, `/lists`) to catalog all physical document library files.
   * **Targeted Site Pages**: Reads `gs://bucket/config/target_urls.txt` to dynamically scope and harvest modern SharePoint site pages (`.aspx`).
   * Extracts clean semantic DOM structure, page titles, author metadata, inline leadership images, accordions, and custom styles.

3. **O(1) Delta Cache & Orphan Pruning**:
   * Maintains an O(1) cache lookup against current GCS bucket objects (`gcs_cache`).
   * Compares SharePoint `lastModifiedDateTime` timestamps against cached GCS generation timestamps. Unchanged items bypass downstream processing instantaneously.
   * Identifies orphaned or deleted SharePoint files and removes the stale objects from GCS to maintain strict 1:1 parity.

4. **High-Fidelity PDF Rendering Engine (`pdf_renderer.py`)**:
   * **Playwright Chromium (Primary)**: Runs inside a containerized runtime (`mcr.microsoft.com/playwright/python:v1.44.0-jammy`). Launches a headless Chromium browser instance, loads harvested HTML layouts, executes complex JavaScript/CSS grid layouts, waits for network idle state, and generates pixel-perfect vector `.pdf` executive reports (~300KB–1.2MB per page).
   * **Intelligent Image URL Resolver**: Automatically resolves enterprise OData endpoints, SharePoint CDN thumbnail tokens, and authenticated inline images before rendering.
   * **WeasyPrint (Fallback)**: Lightweight HTML5 vector compile engine that executes in <2 seconds per page if headless Chromium binaries are not present in the runtime container.

5. **Streaming Parallel Pipelined Chunk Execution & Micro-Batching (`CONFIG_Batch_Size × CONFIG_Max_Parallel_Workers`)**:
   * **Pre-Render Delta Cache Filter**: Modern Site Pages (`.aspx`) are checked against `gcs_cache` during discovery *before* any browser rendering occurs. Unchanged pages bypass rendering instantly (<1ms).
   * **Pipelined Chunk Processing**: Candidate items are processed in self-contained chunks of size `CONFIG_Batch_Size × CONFIG_Max_Parallel_Workers` (e.g., `5 × 5 = 25 items`).
   * **Parallel Playwright Rendering**: Within each chunk, up to `CONFIG_Max_Parallel_Workers` threads concurrently render modern `.aspx` site pages into high-fidelity PDF base64 payloads, achieving up to a 5x speedup over sequential rendering.
   * **Immediate Micro-Batch Orchestration**: As soon as a chunk finishes parallel rendering, its items are sliced into micro-batches (`CONFIG_Batch_Size`) and dispatched immediately to Application Integration (`yourorg-sharepoint-gcs-parent`). Memory is flushed after each chunk, ensuring continuous incremental progress and preventing serverless memory bloat or timeouts.

---

## 2. Integration Pipeline: Cloud Run → Application Integration → GCS & Metadata Maintenance

The synchronization workflow separates orchestration from data transport via Google Cloud Application Integration and dedicated Integration Connectors.

```
       [Cloud Scheduler (Cron Trigger)]
                      │
                      ▼ (HTTPS POST / OIDC Auth)
┌───────────────────────────────────────────────────────────┐
│              Traversal Cloud Run Service                  │
│           (yourorg-sharepoint-list-files)                 │
│                                                           │
│  1. Performs Traversal & Delta Cache Check                │
│  2. Renders Modern .aspx Pages directly to GCS (pages/)   │
│  3. Generates/Updates gs://bucket/config/metadata.jsonl   │
└─────────────────────────────┬─────────────────────────────┘
                              │
                              ▼ (Submits Micro-Batches of Files to Sync)
┌───────────────────────────────────────────────────────────┐
│     Application Integration Parent (Orchestrator)         │
│             (yourorg-sharepoint-gcs-parent)               │
│                                                           │
│  • Loops asynchronously over batched file manifest        │
│  • Emits execution status logs to GCS (config/status/)    │
└─────────────────────────────┬─────────────────────────────┘
                              │
                              ▼ (ForEach File Iteration)
┌───────────────────────────────────────────────────────────┐
│      Application Integration Child (Worker)               │
│              (yourorg-sharepoint-gcs-child)               │
│                                                           │
│  ┌────────────────────────┐      ┌─────────────────────┐  │
│  │  SharePoint Connector  │      │    GCS Connector    │  │
│  │       (V2 API)         │      │      (V1 API)       │  │
│  │                        │      │                     │  │
│  │   Downloads raw stream │────▶ │   Streams uncorrupted│  │
│  │   bytes from M365      │      │   bytes to target   │  │
│  └────────────────────────┘      └─────────────────────┘  │
└───────────────────────────────────────────────────────────┘
```

### Pipeline Execution & Metadata File Lifecycle

1. **Orchestrator Handoff (Parent Integration)**:
   * The Traversal Cloud Run service posts structured JSON micro-batches to the **Parent Integration** (`yourorg-sharepoint-gcs-parent`).
   * The Parent Integration acts as an asynchronous orchestrator, iterating through the file manifest and dispatching individual tasks to the child worker.

2. **Binary Data Streaming (Child Worker & Connectors)**:
   * The **Child Integration** (`yourorg-sharepoint-gcs-child`) invokes the **SharePoint Integration Connector V2** (`CONFIG_SharePoint_Connection`) to stream raw, uncorrupted file bytes directly from Microsoft 365.
   * Bytes are piped instantly through the **GCS Integration Connector V1** (`CONFIG_GCS_Connection`) into the target GCS bucket (`CONFIG_GCS_Bucket`), avoiding memory buffering bottlenecks.

3. **Continuous Metadata File Maintenance (`config/metadata.jsonl`)**:
   * Alongside binary synchronization, the Traversal Service continuously compiles and maintains `gs://YOUR_BUCKET/config/metadata.jsonl`.
   * **Structured JSONL Schema**: Every document and rendered PDF page receives a structured record combining the GCS storage URI (`id`) and custom metadata (`structData`):
     ```json
     {
       "id": "gs://yourorg-bucket-sharepoint-sync/pages/Executive_Strategy.pdf",
       "structData": {
         "title": "Executive Strategy Portal",
         "sharepoint_url": "https://yourorg.sharepoint.com/sites/portal/SitePages/Executive_Strategy.aspx",
         "lastModified": "2026-07-06T12:00:00Z",
         "category": "ModernPage"
       }
     }
     ```
   * Maintaining `sharepoint_url` as a persistent structured attribute guarantees downstream systems can link back to the live SharePoint source instead of raw GCS objects.

---

## 3. End-to-End Agent Assist Architecture: Genesys to SharePoint

When customer service agents handle live interactions inside **Genesys Contact Center**, Google Cloud Generative Knowledge Assist (GKA / CCAI) surfaces contextual answers and citations. The architecture below ensures agents are routed directly to live, interactive SharePoint pages upon clicking citations.

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   END-TO-END AGENT ASSIST ARCHITECTURE                                      │
│                                                                                                             │
│   ┌───────────────────────────────────────────────┐     ┌───────────────────────────────────────────────┐   │
│   │           1. Genesys Agent Desktop            │     │         2. Contact Center AI Widget           │   │
│   │                                               │     │          (<agent-assist-ui-modules>)          │   │
│   │  • Live Customer Call / Chat Session          │────▶│ • Surfaces GenAI summaries & citations        │   │
│   │  • Embeds Google Agent Assist Web Component   │     │ • articleLinkConfig overrides hyperlink       │   │
│   └───────────────────────────────────────────────┘     └───────────────────────┬───────────────────────┘   │
│                                                                                 │                           │
│                                                                                 ▼                           │
│                                                         ┌───────────────────────────────────────────────┐   │
│                                                         │         3. Vertex AI Discovery Engine         │   │
│                                                         │            (Generative Knowledge)             │   │
│                                                         │                                               │   │
│                                                         │ • Indexes documents & metadata attributes     │   │
│                                                         │ • Maps answer snippets to sharepoint_url      │   │
│                                                         └───────────────────────▲───────────────────────┘   │
│                                                                                 │                           │
│                                                           (12-Hour Incremental  │                           │
│                                                              Cron Scheduler)    │                           │
│                                                                                 │                           │
│   ┌───────────────────────────────────────────────┐     ┌───────────────────────┴───────────────────────┐   │
│   │        5. Microsoft 365 SharePoint Intranet   │     │       4. Synchronized GCS Repository          │   │
│   │           (https://maxis.sharepoint.com)      │     │         (gs://yourorg-bucket-sharepoint-sync) │   │
│   │                                               │     │                                               │   │
│   │  • Live Interactive Enterprise Page           │◀────│ • Rendered Executive PDFs (pages/*.pdf)       │   │
│   │  • Enforces M365 Entra ID SSO / Permissions   │     │ • Metadata Manifest (config/metadata.jsonl)   │   │
│   └───────────────────────────────────────────────┘     └───────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### End-to-End Workflow & Citation Resolution

1. **Synchronization & Discovery Ingestion**:
   * **GCS Repository**: The backend Traversal & Integration pipeline keeps PDF snapshots and `config/metadata.jsonl` continuously synchronized in GCS.
   * **12-Hour Automated Scheduler**: A dedicated Cloud Scheduler job (`doddi-sharepoint-datastore-sync-12h`) calls `sync_datastore.py` every 12 hours (`0 */12 * * *`) to ingest `metadata.jsonl` into **Vertex AI Discovery Engine** (`importDocuments` in `INCREMENTAL` mode).

2. **Real-Time Agent Query in Genesys**:
   * During a live customer interaction on **Genesys Agent Desktop**, real-time conversation audio/text triggers **Google Contact Center AI (CCAI) / Agent Assist**.
   * Vertex AI Discovery Engine semantic search retrieves the relevant policy document or modern SharePoint page snapshot and synthesizes an executive answer.

3. **Dynamic Citation Override (`articleLinkConfig`)**:
   * By default, raw vector search citations point to the underlying GCS blob (`gs://bucket/pages/page.pdf`).
   * The Agent Assist widget (`<agent-assist-ui-modules>`) embedded in Genesys is configured with `articleLinkConfig`:
     ```javascript
     kaWidget.config = {
       ...kaWidget.config,
       articleLinkConfig: {
         linkMetadataKey: "sharepoint_url",  // Extracts live URL from metadata.jsonl schema
         target: "_blank"                    // Opens clean new tab in agent browser
       }
     };
     ```
   * When an agent clicks the citation link, the UI automatically intercepts the default blob URL and redirects the browser directly to `sharepoint_url` (`https://maxis.sharepoint.com/...`).

4. **Live SharePoint Navigation & SSO Enforcement**:
   * The agent lands on the official, interactive SharePoint modern page.
   * Microsoft Entra ID SSO automatically verifies the agent's permissions, ensuring security compliance while delivering the most up-to-date intranet experience.
