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

## 4. ⭐ SELECTED OPERATIONAL MODEL: Option 1 (Single Master Scheduler Loop)

Per user alignment (`Option 1 is better`), we standardize on **One Master Cloud Scheduler Job (`Option 1 — Single Loop`)** instead of deploying multiple separate scheduler cron jobs across the day.

### How Option 1 Works in V11:
1. **One Cloud Scheduler Job in GCP Console:** You maintain exactly **ONE** Cloud Scheduler cron job (`yourorg-sharepoint-sync-daily`) that triggers once a day or on your preferred schedule. Zero scheduler management clutter for the customer!
2. **Sequential Category Loop in `main.py`:** When the container wakes up, `main.py` opens `sites-sync.json` and iterates through every category inside `categories[]` one by one:
   * It runs Category 1 (`DEN Root Only` with `include_subsites: false`) $\rightarrow$ discovers items in 5s $\rightarrow$ syncs delta $\rightarrow$ writes shard `categories/den-root/config/metadata_part.jsonl`.
   * It runs Category 2 (`Business`) $\rightarrow$ discovers items in 15s $\rightarrow$ syncs delta $\rightarrow$ writes shard `categories/business/config/metadata_part.jsonl`.
   * It runs Category 3 (`Consumer`) $\rightarrow$ discovers items in 15s $\rightarrow$ syncs delta $\rightarrow$ writes shard `categories/consumer/config/metadata_part.jsonl`.
   * *(And so on through the 6 category groups!)*
3. **Master Metadata Aggregation at the Very End:** Once all categories in the loop have finished syncing, `main.py` executes `combine_metadata_shards()` ONCE right before exiting! That combines all sharded files into one master `gs://<bucket>/config/metadata.jsonl` containing all 38,823 items for Vertex AI Search (`AgentAssist`).
4. **Optional Single-Category On-Demand Overrides:** If Janice *ever* needs an urgent 2-minute sync for JUST ONE category (e.g. HR just updated 20 urgent SOPs at 3:00 PM), she can still pass an override parameter:
   ```bash
   gcloud run jobs execute <YOUR-JOB-NAME> --update-env-vars="TARGET_CATEGORY_ID=tier1-business"
   ```
   If `TARGET_CATEGORY_ID` is present, `main.py` runs ONLY that category and skips the loop! If absent, `main.py` runs the full master loop!

---

## 5. 🚨 THE DUPLICATE CRAWL DILEMMA (`include_subsites: false`)

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
* But when Category 1 (`sites/DEN Root Portal`) runs in the master loop, `get_all_subsites_recursive()` will automatically traverse downwards into `Consumer` and `Business` all over again, attempting to sync **all 38,823 items** across the entire tenant!
* **Result:** Extreme duplication of GCS objects, wasted API bandwidth, and redundant file processing!

---

### 💡 THE V11 CODE SOLUTION: `"include_subsites": false` (Exact Target / Non-Recursive Mode)

To prevent this duplication, **we MUST update `cf-sharepoint/main.py` inside `v11-percategory`** to support a new parameter/flag: `"include_subsites"` (or `"recursive"`), defaulting to `true` for backward compatibility, but allowing `false` when targeting root site collections that have separate child category jobs.

#### How It Works in `sites-sync.json`:
```json
{
  "root_portal_site": "sites/DEN",
  "categories": [
    {
      "category_id": "tier1-den-root-only",
      "display_name": "DEN Root Portal Documents & Guides ONLY",
      "sharepoint_site": "sites/DEN",
      "include_subsites": false,        <-- 🚨 PREVENTS DOWNWARD CRAWL INTO CHILD DEPARTMENTS!
      "sharepoint_library": "all",
      "gcs_destination_prefix": "categories/den-root/"
    },
    {
      "category_id": "tier1-business",
      "display_name": "Business Department Policies & Documents",
      "sharepoint_site": "sites/DEN/Business",
      "include_subsites": true,         <-- Crawls Business + any sub-teams inside Business
      "sharepoint_library": "all",
      "gcs_destination_prefix": "categories/business/"
    },
    {
      "category_id": "tier1-consumer",
      "display_name": "Consumer Department SOPs & Guides",
      "sharepoint_site": "sites/DEN/Consumer",
      "include_subsites": true,         <-- Crawls Consumer + any sub-teams inside Consumer
      "sharepoint_library": "all",
      "gcs_destination_prefix": "categories/consumer/"
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

#### The Operational Guarantee:
* At any given second during the Option 1 Master Loop, the container's RAM and the Microsoft Graph API connection **ONLY discover and process the exact items belonging to that single category**!
* When Category 1 finishes its 4,076 items, `main.py` **clears the discovery inventory from memory (`target_sites_to_scan.clear()`) and closes the session** before moving to Category 2.
* **We NEVER discover or process all 38,823 items at the same time in memory or in one single OData discovery burst again!**

---

## 6. 🧠 THE VERTEX AI SEARCH STRATEGY: Master Aggregated `metadata.jsonl`

A critical enterprise requirement for Vertex AI Search (`AgentAssist`) is that **Vertex AI Unstructured Data Stores with Metadata (`gcs_store`) can only ingest from a SINGLE central `metadata.jsonl` catalog** located in the root bucket (`gs://<bucket>/config/metadata.jsonl`). Vertex AI Search cannot natively read 25 fragmented metadata files scattered across category subfolders without creating 25 separate data stores!

Furthermore, each line of `metadata.jsonl` **must maintain both `source_url` (pointing to GCS for text extraction) and `sharepoint_url` (pointing to M365 for chatbot citation hyperlinks)**.

### ⭐ The Solution: Sharded Category Metadata + Automatic Master Aggregator (`combine_metadata_shards`)

To solve this cleanly with **zero race conditions and 100% metadata preservation**, V11 implements a **Sharded Write + Atomic Master Aggregation** architecture:

```
[ gs://doddi-bucket-sharepoint-sync-20260709-v2/ ]
 │
 ├── categories/business/config/metadata_part.jsonl   <-- Shard 1 (Written by Business job: 9,599 lines)
 ├── categories/consumer/config/metadata_part.jsonl   <-- Shard 2 (Written by Consumer job: 8,256 lines)
 ├── categories/den-root/config/metadata_part.jsonl   <-- Shard 3 (Written by DEN Root job: 4,076 lines)
 │
 └── ⚡ combine_metadata_shards() (Executes automatically once when the master category loop completes)
      │
      ▼
 📂 config/metadata.jsonl                             <-- Master Unified Catalog (All 38,823 lines for Vertex AI!)
```

#### 1. Sharded Category Writes During the Sync Loop
When each category inside the loop (`Business`, `Consumer`, etc.) runs, it updates **only its own sharded metadata file** inside its category folder:
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
At the very end of `main.py` inside `v11-percategory` (after the loop finishes all categories), `main.py` automatically executes a fast 3-second **Master Aggregation Function**:
1. **List all shards:** Queries GCS for `gs://<bucket>/categories/*/config/metadata_part.jsonl` (plus any legacy root `config/metadata.jsonl`).
2. **In-Memory Merge & Deduplication:** Streams and combines all lines into a single master dictionary in memory (`O(1)` deduplication by `id` / `source_url`).
3. **Atomic Master Upload:** Uploads the combined master file directly to **`gs://<bucket>/config/metadata.jsonl`**!

---

## 7. 🔍 DIAGNOSTIC MECHANISMS: `check_syncall_before.py` & `check_syncall_after.py` in V11

In V11, our pre-flight and post-flight verification scripts (`check/check_syncall_before.py` and `check/check_syncall_after.py`) are updated to mirror the exact same `sites-sync.json` Category Matrix and support **two execution modes**:

### Mode A: Targeted Single-Category Check (`Fast Audit Mode`) ⭐
If an operator wants to check only the status of one specific department right before or right after a sync:
```bash
python3 check/check_syncall_before.py --category=tier1-business
```
* **Behavior:** Opens `sites-sync.json`, finds `tier1-business`, connects strictly to `sites/DEN/Business`, evaluates timestamps against `gs://<bucket>/categories/business/`, and outputs that single category's exact report in **<15 seconds**!

### Mode B: Master Serial Category-by-Category Loop (`Full Tenant Audit Mode`)
If run without `--category`:
```bash
python3 check/check_syncall_before.py
```
* **Behavior:** Instead of running one massive 20-minute discovery burst across 59 libraries simultaneously, the diagnostic script loops through `sites-sync.json` sequentially (or with parallel category workers), cleans up memory after each category, and prints a **Unified Category Summary Report Table**:

```
================================================================================
📊 V11 PRE-SYNC AUDIT: CATEGORY BY CATEGORY INVENTORY & DELTA SUMMARY
================================================================================
No.  Category ID                Display Name                Target   Delta  Skipped
--------------------------------------------------------------------------------
1    tier1-den-root-only        DEN Root Portal ONLY        4076     0      4076   
2    tier1-business             Business Department         9599     12     9587   
3    tier1-consumer             Consumer Department         8256     0      8256   
4    tier1-hotlink              Hotlink Department          5265     0      5265   
5    tier1-system-procedure     System & Procedure          4320     5      4315   
6    tier2-medium-departments   Channels, Solutions & QA    4887     0      4887   
7    tier3-specialized-teams    MEPS, Credit, BCP, FAQ...   2420     0      2420   
--------------------------------------------------------------------------------
     TOTAL INVENTORY ACROSS ALL CATEGORIES                  38823    17     38806  
================================================================================
```
