# V11 Enterprise Per-Category Synchronization & Agent Assist Architecture (`v11-percategory`)

This architectural blueprint describes the **Version 11 Per-Category Synchronization Pipeline** (`v11-percategory`). Built for massive enterprise footprints (e.g., 35,000+ items across 20+ subsite departments), V11 replaces monolithic crawling with an **isolated, sharded category matrix**, **decoupled transport routing**, and **O(1) sharded metadata aggregation**.

---

## 1. V11 Multi-Tier Category Matrix & Master Serial Loop

Instead of scanning an entire tenant in one monolithic run, V11 divides your SharePoint site collection into manageable, prioritized slices defined in `config-category.json`. The **Traversal Cloud Run Service** (`doddi-sharepoint-list-files-20260709-v2`) executes an **Option 1 Master Serial Loop**, iterating sequentially across each `"active": "yes"` category according to its `"order_to_sync"`.

```
       [ Cloud Scheduler / Manual Execution Trigger ]
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                 TRAVERSAL CLOUD RUN SERVICE (main.py)                       │
│                                                                             │
│  Loads config-category.json -> Iterates Active Categories Sequentially:     │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Loop 1: tier1-den-root-only (order_to_sync: 1)                        │  │
│  │ ├─ Target: sites/DEN (Root only, Include Subsites: False)             │  │
│  │ └─ Shard Prefix: categories/den-root/                                 │  │
│  └───────────────────────────────────┬───────────────────────────────────┘  │
│                                      ▼ [Wipes RAM Buffer & Proceeds]        │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Loop 2: tier1-business (order_to_sync: 2)                             │  │
│  │ ├─ Target: sites/DEN/Business (Include Subsites: True)                │  │
│  │ └─ Shard Prefix: categories/business/                                 │  │
│  └───────────────────────────────────┬───────────────────────────────────┘  │
│                                      ▼ [Wipes RAM Buffer & Proceeds]        │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │ Loop 3..X: tier2-medium / tier3-specialized (Multi-Site Arrays)       │  │
│  │ ├─ Target: ["sites/DEN/Channels", "sites/DEN/MEPS", ...]              │  │
│  │ └─ Shard Prefix: categories/medium-departments/ | specialized-teams/  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Architectural Advantages:
* **Multi-Site Array Ingestion:** Categories can accept either a single site (`"sites/DEN/Business"`) or a JSON array of multiple distinct subsites (`["sites/DEN/Channels", "sites/DEN/Quality-Assurance"]`), routing all of them cleanly into one unified GCS prefix shard.
* **RAM & Timeout Isolation:** After each category completes its discovery, Playwright rendering, and upload handoff, `main.py` explicitly flushes its memory buffers before starting the next category. This eliminates `Out-Of-Memory (OOM)` container crashes and Cloud Run `86,400s` timeout breaches.

---

## 2. Decoupled Transport Routing: SharePoint URL vs. GCS Sharded Storage

A critical challenge in category-based synchronization is that while files must be stored in sharded GCS folders (`categories/<id>/files/...`), those sharded prefix folders **do not exist on Microsoft SharePoint**. 

V11 solves this via **Decoupled Transport Routing** between the discovery engine (`sharepoint_traversal.py`), the orchestrator (`parent_workflow`), and the data transport worker (`child_workflow`).

```
┌───────────────────────────────────────────────────────────────────────────────────────────────────┐
│                          DECOUPLED TRANSPORT ROUTING MECHANISM                                    │
│                                                                                                   │
│  Discovery Engine (list_drive_items_recursive) emits two decoupled paths per item:               │
│                                                                                                   │
│  1️⃣  Url (Remote SharePoint Source)  : https://priyambodo.sharepoint.com/.../Policy.docx         │
│  2️⃣  RelativePath (GCS Shard Target) : categories/business/files/Business/Policy.docx             │
└─────────────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                                  │
                                                  ▼ (POST Micro-Batches via API Trigger)
┌───────────────────────────────────────────────────────────────────────────────────────────────────┐
│               APPLICATION INTEGRATION PARENT & CHILD TRANSPORT PIPELINE                           │
│                                                                                                   │
│  ┌──────────────────────────────────────────┐      ┌───────────────────────────────────────────┐  │
│  │        Task 2: SharePoint Connector      │      │          Task 4: GCS Connector            │  │
│  │                                          │      │                                           │  │
│  │  Reads: Url                              │      │  Reads: RelativePath (via folderPath)     │  │
│  │  Action: DownloadDocument                │─────▶│  Action: UploadObject                     │  │
│  │  Target: https://.../Policy.docx         │      │  Target: categories/business/files/...    │  │
│  │  Result: 100% Valid (0% 404 Errors)      │      │  Result: Isolated Sharded GCS Storage     │  │
│  └──────────────────────────────────────────┘      └───────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Exact Routing Logic:
1. **SharePoint Retrieval (`Url`):** The item's `Url` is strictly constructed using the actual SharePoint folder hierarchy (`https://priyambodo.sharepoint.com/sites/DEN/Business/Policy.docx`). When the Child Integration (`Task 2`) asks the Microsoft Graph connector to download the file, it retrieves the bytes with **0% `HTTP 404` errors**.
2. **GCS Sharded Storage (`RelativePath`):** The item's `RelativePath` explicitly includes the category shard (`categories/business/files/Business/Policy.docx`). The Child Integration (`Task 3` / `Task 5` Jsonnet mappings) extracts this exact sharded folder path and instructs the GCS connector (`Task 4` / `Task 7`) to drop the uncorrupted stream bytes precisely inside that sharded folder.

---

## 3. Sharded Metadata Aggregation (`combine_metadata_shards`)

To allow Vertex AI Search and Contact Center AI (CCAI) to index your entire enterprise repository in O(1) time without reading tens of thousands of individual GCS blobs, V11 implements **Sharded Manifest Architecture**.

```
┌───────────────────────────────────────────────────────────────────────────────────────────────────┐
│                            SHARDED METADATA AGGREGATION PIPELINE                                  │
│                                                                                                   │
│  During Category Loops (Step 1-6): Every active category writes its own isolated manifest shard:  │
│                                                                                                   │
│  • gs://doddi-bucket-v2/categories/den-root/config/metadata_part.jsonl         (20 records)       │
│  • gs://doddi-bucket-v2/categories/business/config/metadata_part.jsonl         (9,599 records)    │
│  • gs://doddi-bucket-v2/categories/medium-departments/config/metadata_part.jsonl (4,887 records)  │
└─────────────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                                  │
                                                  ▼ (Final Step 7 of Master Loop)
┌───────────────────────────────────────────────────────────────────────────────────────────────────┐
│                             MASTER AGGREGATOR (combine_metadata_shards)                           │
│                                                                                                   │
│  Scans gs://doddi-bucket-v2/categories/*/config/metadata_part.jsonl                               │
│  Stream-merges all category shards and writes the unified master manifest:                        │
│                                                                                                   │
│  👉 gs://doddi-bucket-v2/config/metadata.jsonl (100% of all 38,823 enterprise records)            │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Record Structure inside `metadata.jsonl`:
Every entry in the final `config/metadata.jsonl` provides exact sharded GCS routing alongside the original live SharePoint web URL:
```json
{
  "id": "Policy_Doc_2026",
  "structData": {
    "title": "Business Policy Document 2026",
    "sharepoint_url": "https://priyambodo.sharepoint.com/sites/DEN/Business/Policy.docx",
    "category_id": "tier1-business",
    "category_name": "Business Department Policies & Documents",
    "relative_path": "categories/business/files/Business/Policy.docx"
  },
  "content": {
    "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "uri": "gs://doddi-bucket-sharepoint-sync-20260709-v2/categories/business/files/Business/Policy.docx"
  }
}
```

---

## 4. End-to-End Agent Assist Architecture: Genesys to SharePoint

When customer service agents handle live interactions inside **Genesys Contact Center**, Google Cloud Generative Knowledge Assist (GKA / CCAI) queries Vertex AI Search and surfaces contextual answers and citations.

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
│                                                         │ • Indexes sharded config/metadata.jsonl       │   │
│                                                         │ • Maps answer snippets to sharepoint_url      │   │
│                                                         └───────────────────────▲───────────────────────┘   │
│                                                                                 │                           │
│                                                           (12-Hour Incremental  │                           │
│                                                              Cron Scheduler)    │                           │
│                                                                                 │                           │
│   ┌───────────────────────────────────────────────┐     ┌───────────────────────┴───────────────────────┐   │
│   │        5. Microsoft 365 SharePoint Intranet   │     │       4. Synchronized GCS Sharded Storage     │   │
│   │           (https://yourorg.sharepoint.com)      │     │         (gs://doddi-bucket-...-v2)            │   │
│   │                                               │     │                                               │   │
│   │  • Live Interactive Enterprise Page / File    │◀────│ • Sharded Files (categories/*/files/*)        │   │
│   │  • Enforces M365 Entra ID SSO / Permissions   │     │ • Sharded Pages (categories/*/pages/*.pdf)    │   │
│   └───────────────────────────────────────────────┘     └───────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Citation Resolution Workflow:
1. **Continuous Ingestion:** A dedicated Cloud Scheduler job (`doddi-sharepoint-datastore-sync-20260709-v2`) calls `sync_datastore.py` every 12 hours (`0 */12 * * *`) to ingest the master `config/metadata.jsonl` directly into **Vertex AI Discovery Engine** (`importDocuments` in `INCREMENTAL` mode).
2. **Dynamic Citation Redirect:** By default, raw vector search citations point to the sharded GCS blob (`uri`). The Agent Assist widget embedded inside Genesys uses `articleLinkConfig` to intercept the citation click:
   ```javascript
   kaWidget.config = {
     ...kaWidget.config,
     articleLinkConfig: {
       linkMetadataKey: "sharepoint_url",  // Dynamically extracts live URL from metadata.jsonl structData
       target: "_blank"                    // Opens clean new tab in agent browser
     }
   };
   ```
3. **SSO & Live Intranet Access:** When an agent clicks any citation, the browser opens the exact, live Microsoft SharePoint page or document (`sharepoint_url`). Microsoft Entra ID SSO validates the agent's permissions in real time, guaranteeing enterprise governance and security compliance while delivering the most up-to-date intranet experience.
