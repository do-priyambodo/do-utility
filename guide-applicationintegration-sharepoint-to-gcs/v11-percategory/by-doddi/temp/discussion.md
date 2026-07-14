# 💬 V11 Category-Based SharePoint-to-GCS Synchronization Architecture & Brainstorm (`discussion.md`)

## 1. The Context & Why We Are Evolving to V11 (`The Problem with Monoliths`)

Based on the live discovery audit of the customer's enterprise portal (`Janice @ Maxis — sites/DEN`, preserved in `temp/sample-sites.txt`), synchronizing the entire site collection inside a single continuous execution creates extreme operational and architectural friction:
* **The Scale:** The customer's portal contains **23 distinct child subsites / departments** spanning **59 separate document libraries** and **1 Site Pages library**, totaling **38,823 items** (`33,412 files` + `5,411 modern site pages`).
* **Discovery & Crawl Bottlenecks:** Simply traversing and counting all 59 document libraries across 23 subsites sequentially or inside one container takes **~1,243 seconds (~20.7 minutes)** before a single file or page even begins downloading!
* **High Blast Radius:** A rate-limit throttling event (`429 Too Many Requests`), temporary network glitch, or corrupted `.aspx` canvas page on one deep subsite can disrupt or complicate the synchronization of all 38,000+ items.
* **Flat Data Lake Structure:** Enterprise chatbots and RAG (Retrieval-Augmented Generation) search engines perform significantly better when knowledge is cleanly partitioned by domain/category inside Google Cloud Storage (`gs://<YOUR-BUCKET>/HR/`, `gs://<YOUR-BUCKET>/Finance/`) rather than dumped into a single flat repository along with decorative website banner images.

---

## 2. Customer Inventory Analysis: The 3-Tier Distribution (`From sample-sites.txt`)

Analyzing the exact 38,823-item breakdown reveals that **not all departments are equal**. The inventory follows a steep Pareto distribution:

```
================================================================================
📊 SHAREPOINT SITE COLLECTION DEPARTMENT BREAKDOWN (ASSETS BY SUBSITE)
================================================================================
No.  Subsite / Department Name           Files       Pages       Total     
--------------------------------------------------------------------------------
1    Assisted                            6           15          21        
2    BCP                                 237         33          270       
3    Business                            8456        1143        9599      🚨 Tier 1
4    CDPU                                10          3           13        
5    ChannelMarketing                    1056        1           1057      🟡 Tier 2
6    Channels                            1786        1           1787      🟡 Tier 2
7    Consumer                            6369        1887        8256      🚨 Tier 1
8    Credit-Operations                   220         110         330       
9    Customer-Support                    0           13          13        
10   Customer_First                      0           13          13        
11   DEN (Root Portal)                   4056        20          4076      🚨 Tier 1
12   DistributionMgmt                    0           5           5         
13   Enterprise-Solutions                1080        49          1129      🟡 Tier 2
14   FAQ                                 0           590         590       
15   Hotlink                             4093        1172        5265      🚨 Tier 1
16   MEPS                                391         14          405       
17   Quality-Assurance                   855         59          914       🟡 Tier 2
18   Quicklinks                          6           0           6         
19   Retail                              491         91          582       
20   Self_Serve                          44          42          86        
21   Service-Insights                    0           1           1         
22   System-Procedure                    4182        138         4320      🚨 Tier 1
23   Training                            74          11          85        
--------------------------------------------------------------------------------
     TOTAL INVENTORY ACROSS SITE         33412       5411        38823     
================================================================================
```

### 🏆 The 3-Tier Sharding Strategy:
* **🚨 Tier 1 (The 5 Mega-Categories — 31,516 items / 81% of total):** `Business` (9,599), `Consumer` (8,256), `Hotlink` (5,265), `System-Procedure` (4,320), and `DEN Root` (4,076).
* **🟡 Tier 2 (The 4 Medium Categories — 4,887 items / 12.5% of total):** `Channels` (1,787), `Enterprise-Solutions` (1,129), `ChannelMarketing` (1,057), and `Quality-Assurance` (914).
* **🟢 Tier 3 (The 14 Lightweight Categories — 2,420 items / 6.2% of total):** `MEPS` (405), `Credit-Operations` (330), `BCP` (270), `Retail` (582), `FAQ` (590), plus 9 tiny departments (<100 items each).

---

## 3. The Core Architectural Breakthrough: Separation of Concerns

To permanently solve the 20-minute discovery bottleneck and eliminate timeouts without requiring engineering intervention, V11 decouples **Infrastructure/Authentication** from **Business Target Scope**:

```
[ parameters.json ] (Static Infra & Auth)       [ sites-sync.json ] (Dynamic Category Matrix)
 ├── GCP Project ID                              ├── Category 1: Business (prefix: /business/)
 ├── M365 Tenant / Client IDs                    ├── Category 2: Consumer (prefix: /consumer/)
 ├── Secret Manager Path                         └── Category 3: Lightweight Batch (prefix: /ops/)
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

## 4. 🚨 THE DUPLICATE CRAWL DILEMMA (`include_subsites: false`)

When separating `sites/DEN` (the root portal) from its child departments (`sites/DEN/Consumer`, `sites/DEN/Business`, etc.) inside a Category Matrix, we face a critical architectural challenge with our legacy V10 discovery loop:

### The Problem in Legacy V10 Code (`get_all_subsites_recursive`)
In `v10-10Jul2026/by-doddi/cf-sharepoint/main.py`, when the crawler receives a target site path (`CONFIG_Sharepoint_Sites = "sites/DEN"`), it automatically executes:
```python
target_sites_to_scan = get_all_subsites_recursive("sites/DEN", headers)
```
What `get_all_subsites_recursive()` does:
1. It queries the root site (`DEN`), finding its 4,076 root items.
2. It queries Microsoft Graph API for `/sites/DEN:/subsites` (or `/children`), which returns **all 24 child departments** (`DEN/Consumer`, `DEN/Business`, `DEN/System-Procedure`, etc.)!
3. It recursively traverses every child subsite down to the bottom of the tree.

**Why this creates massive duplication if left unchanged in V11:**
If we create `sites-sync.json` with Category 1 (`sites/DEN`), Category 2 (`sites/DEN/Consumer`), and Category 3 (`sites/DEN/Business`):
* When Category 2 (`Consumer`) runs, it syncs **8,256 items**.
* When Category 3 (`Business`) runs, it syncs **9,599 items**.
* But when Category 1 (`sites/DEN Root Portal`) runs, `get_all_subsites_recursive()` will automatically traverse downwards into `Consumer` and `Business` all over again, attempting to sync **all 38,823 items** across the entire tenant!
* **Result:** Extreme duplication of GCS objects, wasted API bandwidth, and redundant file processing!

---

### 💡 THE V11 CODE SOLUTION: `"include_subsites": false` (Exact Target / Non-Recursive Mode)

To prevent this duplication, **we MUST update `cf-sharepoint/main.py` inside `v11-percategory`** to support a new parameter/flag: `"include_subsites"` (or `"recursive"`), defaulting to `true` for backward compatibility, but allowing `false` when targeting root site collections that have separate child category jobs.

#### How It Works:
We add `"include_subsites"` to our category entries inside `sites-sync.json` (or `parameters.json`):

```json
{
  "categories": [
    {
      "category_id": "tier1-den-root-only",
      "display_name": "DEN Root Portal Documents & Guides ONLY",
      "sharepoint_site": "sites/DEN",
      "include_subsites": false,        <-- 🚨 PREVENTS DOWNWARD CRAWL INTO CHILD DEPARTMENTS!
      "sharepoint_library": "Documents",
      "gcs_destination_prefix": "categories/den-root/",
      "cron_schedule": "0 0 * * *"
    },
    {
      "category_id": "tier1-business",
      "display_name": "Business Department Policies & Documents",
      "sharepoint_site": "sites/DEN/Business",
      "include_subsites": true,         <-- Crawls Business + any sub-teams inside Business
      "sharepoint_library": "Documents",
      "gcs_destination_prefix": "categories/business/",
      "cron_schedule": "0 2 * * *"
    },
    {
      "category_id": "tier1-consumer",
      "display_name": "Consumer Department SOPs & Guides",
      "sharepoint_site": "sites/DEN/Consumer",
      "include_subsites": true,         <-- Crawls Consumer + any sub-teams inside Consumer
      "sharepoint_library": "Documents",
      "gcs_destination_prefix": "categories/consumer/",
      "cron_schedule": "0 4 * * *"
    }
  ]
}
```

#### Required Code Change in `v11-percategory/by-doddi/cf-sharepoint/main.py`:
We modify the discovery initialization in `main.py` so that if `include_subsites` (or `recursive`) is `False`, we **skip `get_all_subsites_recursive()`** and inspect only the exact target site:

```python
# Check if the category configuration requests non-recursive / root-only discovery
include_subsites = req_data.get("include_subsites", params.get("CONFIG_Include_Subsites", True))

if not include_subsites:
    print(f"🎯 Non-Recursive / Exact Target Mode Active ('include_subsites': False)")
    print(f"   Inspecting only root site '{CONFIG_Sharepoint_Sites}' without crawling child departments.")
    # Resolve only the root site object without calling get_all_subsites_recursive()
    root_site_obj = resolve_site_info(CONFIG_Sharepoint_Sites, headers)
    target_sites_to_scan = [root_site_obj] if root_site_obj else []
else:
    print(f"🏢 Recursive Discovery Mode Active ('include_subsites': True)")
    target_sites_to_scan = get_all_subsites_recursive(CONFIG_Sharepoint_Sites, headers)
```

#### The Operational Result with `include_subsites: false`:
1. When Category 1 (`sites/DEN` with `include_subsites: false`) runs: It scans only the libraries directly attached to `sites/DEN` (exactly those **4,076 root items**). It **never** crawls `Consumer` or `Business`. $\rightarrow$ **0 Duplicates!**
2. When Category 2 (`sites/DEN/Consumer` with `include_subsites: true`) runs: It scans only `Consumer` (and its sub-teams, exactly those **8,256 items**). $\rightarrow$ **0 Duplicates!**
3. When Category 3 (`sites/DEN/Business` with `include_subsites: true`) runs: It scans only `Business` (exactly those **9,599 items**). $\rightarrow$ **0 Duplicates!**

---

## 6. 🧠 THE VERTEX AI SEARCH STRATEGY: Master Aggregated `metadata.jsonl`

A critical enterprise requirement for Vertex AI Search (`AgentAssist`) is that **Vertex AI Unstructured Data Stores with Metadata (`gcs_store`) can only ingest from a SINGLE central `metadata.jsonl` catalog** located in the root bucket (`gs://<bucket>/config/metadata.jsonl`). Vertex AI Search cannot natively read 25 fragmented metadata files scattered across category subfolders without creating 25 separate data stores!

Furthermore, each line of `metadata.jsonl` **must maintain both `source_url` (pointing to GCS for text extraction) and `sharepoint_url` (pointing to M365 for chatbot citation hyperlinks)**.

### The Problem with Concurrent Writes
If Category 1 (`Business`) and Category 2 (`Consumer`) run at different times or concurrently, and both try to overwrite the single root `gs://<bucket>/config/metadata.jsonl` directly during their sync loop, we risk:
1. **Lost Writes / Race Conditions:** One category overwrites and erases the metadata of the other category!
2. **O(n) Rewriting Bottlenecks:** Re-downloading and rewriting a 38,000-line JSONL file after every single file sync slows down the crawler.

### ⭐ The Solution: Sharded Category Metadata + Automatic Master Aggregator (`combine_metadata_shards`)

To solve this cleanly with **zero race conditions and 100% metadata preservation**, V11 implements a **Sharded Write + Atomic Master Aggregation** architecture:

```
[ gs://doddi-bucket-sharepoint-sync-20260709-v2/ ]
 │
 ├── categories/business/config/metadata_part.jsonl   <-- Shard 1 (Written by Business job: 9,599 lines)
 ├── categories/consumer/config/metadata_part.jsonl   <-- Shard 2 (Written by Consumer job: 8,256 lines)
 ├── categories/den-root/config/metadata_part.jsonl   <-- Shard 3 (Written by DEN Root job: 4,076 lines)
 │
 └── ⚡ combine_metadata_shards() (Executes automatically at end of any job run)
      │
      ▼
 📂 config/metadata.jsonl                             <-- Master Unified Catalog (All 38,823 lines for Vertex AI!)
```

#### 1. Sharded Category Writes During the Sync Loop
When each category job (`Business`, `Consumer`, etc.) runs, it writes and updates **only its own sharded metadata file** inside its category folder:
* `Business` updates `gs://<bucket>/categories/business/config/metadata_part.jsonl`
* `Consumer` updates `gs://<bucket>/categories/consumer/config/metadata_part.jsonl`

**Exact Schema Preserved on Every Line:**
```json
{
  "id": "b!CSD9vP0fdkKz8_...",
  "structData": {
    "title": "2026_Enterprise_Strategy.pdf",
    "category": "Business",
    "sharepoint_url": "https://maxis.sharepoint.com/sites/DEN/Business/Documents/2026_Enterprise_Strategy.pdf",
    "source_url": "gs://doddi-bucket-sharepoint-sync-20260709-v2/categories/business/files/2026_Enterprise_Strategy.pdf",
    "last_modified": "2026-07-14T10:00:00Z"
  }
}
```

#### 2. Automatic Master Aggregation Step (`combine_metadata_shards`)
At the very end of `main.py` inside `v11-percategory` (after a category finishes downloading its delta files), `main.py` automatically executes a fast 3-second **Master Aggregation Function**:
1. **List all shards:** Queries GCS for `gs://<bucket>/categories/*/config/metadata_part.jsonl` (plus any legacy root `config/metadata.jsonl`).
2. **In-Memory Merge & Deduplication:** Streams and combines all lines into a single master dictionary in memory (`O(1)` deduplication by `id` / `source_url`).
3. **Atomic Master Upload:** Uploads the combined master file directly to **`gs://<bucket>/config/metadata.jsonl`**!

#### 🚀 Why This Master Aggregator Strategy Is Perfect for Vertex AI:
* **One Single Source of Truth:** Vertex AI Search (`gcs_store`) points strictly to `gs://<bucket>/config/metadata.jsonl`. Whenever any department finishes a sync, `metadata.jsonl` is immediately refreshed containing **100% of all items across every department**!
* **100% Citation Link Preservation:** Both `source_url` (where Vertex AI reads the PDF content in GCS) and `sharepoint_url` (where the `AgentAssist` chatbot generates clickable M365 URLs for human agents) are perfectly preserved for every single item!
* **Zero Race Conditions:** Because each category writes strictly to its own `metadata_part.jsonl` shard during the heavy traversal loop, department syncs can run concurrently without ever locking or corrupting the master file!

---

## 7. Next Steps & Action Plan for Preparation

1. **Align on Option 2 vs Option 1:** Confirm with the project team tomorrow that the **Rich Category Matrix (`Option 2`)** is the preferred schema for the AI knowledge base.
2. **Draft the Initial `sites-sync.json` Matrix:** Identify the top 3 to 5 high-priority departments or subsite paths from the `DEN` hierarchy to include in the initial V11 launch.
3. **Refine `main.py` to Support `sites-sync.json` & `include_subsites`:** Update the discovery engine so that if `sites-sync.json` exists, it iterates over `categories[]` and applies the specific `gcs_destination_prefix`, `sharepoint_library`, and `include_subsites` overrides dynamically.
4. **Implement `combine_metadata_shards()`:** Add the atomic master aggregator helper to `main.py` to ensure Vertex AI Search always has a fresh, unified 38,823-line `metadata.jsonl` catalog at the root!
