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

## 3. 🚨 THE DUPLICATE CRAWL DILEMMA (`Why We MUST Change Code in V11`)

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

## 5. Summary of V11 Required Code & Schema Updates

When we begin development inside `v11-percategory`:
1. **Update `cf-sharepoint/main.py`:** Add the `include_subsites` boolean check around `get_all_subsites_recursive()`.
2. **Update `sites-sync.json` Schema:** Include `"include_subsites": false` on the root `sites/DEN` entry so that the 4,076 root items are cleanly separated from the 34,747 child subsite items without duplication.
3. **Update `validate_params.py`:** Ensure our validation script checks for valid `include_subsites` boolean syntax.
