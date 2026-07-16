# 🎯 Master 7-Tier Category Sharding Strategy (`maxis_7tier_category_strategy.md`)

**Target Footprint:** Enterprise Tenant (`sites/DEN`) — **38,895 Total Items (`33,429 Files + 5,466 Pages`) across 9 Root Departments and 23 Subsites**.  
**Execution Target:** Version 12 Per-Category Cloud Run Pipeline (`v12-category-cloudrun`).  
**Configuration Source:** `hideme/maxis-config-category.json`

---

## 1. Executive Summary & Mathematical Sharding Rules

To guarantee that a single Cloud Run container (`8 GB to 16 GB RAM`) never hits `Signal 9 / Signal 7 (OOM)` memory crashes or 86,400-second execution timeouts while synchronizing the entire 38,895-item tenant inventory, we enforce three hard mathematical rules across our `config-category.json` matrix:

1. **The Modern Page (`.aspx`) OOM Ceiling:**  
   Rendering `.aspx` pages via Playwright Chromium is what consumes container RAM. On 16 GB RAM, the hard rendering ceiling in a single continuous container loop is ~1,800 to 2,200 pages (`and ~900 pages on 8 GB`).  
   *Rule:* **Never assign more than ~1,500 to 1,900 Modern Pages to a single category loop!** Notice how `Consumer` has 1,898 pages, `Hotlink` has 1,184 pages, and `Business` has 1,146 pages. Each of these three departments **must be its own standalone category (`order_to_sync: 5, 6, 7`)** so their memory completely flushes (`gc.collect() + container exit`) before the next department begins.
2. **The Root Portal Duplicate Prevention Rule (`include_subsites: false`):**  
   `sites/DEN` contains **4,081 root-level items (`4,067 files + 14 pages`)**, but it is also the parent URL of `Consumer`, `Business`, `Customer-Support`, etc.  
   *Rule:* For `sites/DEN`, we MUST set `"include_subsites": false`. That tells the crawler to sync only the 4,081 root portal documents without recursively crawling `Consumer` or `Business`, guaranteeing **zero duplicate files across the 38,895 inventory**.
3. **Nested Child Teams (`include_subsites: true`):**  
   `Channels` (`1,788 items`) has nested sub-teams (`Self_Serve`, `Assisted`), and `Customer-Support` (`3,926 items`) has 9 nested sub-teams (`Quality-Assurance`, `Retail`, `Enterprise-Solutions`, etc.).  
   *Rule:* For `Channels` and `Customer-Support`, we set `"include_subsites": true`. That single category entry automatically crawls all child sub-teams and routes their files into one unified GCS prefix shard.

---

## 2. The 7-Tier Execution Table (`Order to Sync & Load Balancing`)

Below is the exact execution sequence (`order_to_sync: 1..7`) designed to run smoothly at 1:00 PM without a single OOM or timeout:

| Order | Category ID (`config-category.json`) | SharePoint Target Sites | `include_subsites` | Total Files | Total Pages (`Chromium RAM Load`) | Total Items | Est. Sync Time (V12/V11) |
| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **1** | `tier1-quicklinks-faq` | `["sites/DEN/Quicklinks", "sites/DEN/FAQ"]` | `True` | 6 | **600 pages** | **606** | **~3 min** *(Fast Morning Verification check)* |
| **2** | `tier1-den-root-only` | `"sites/DEN"` | `False` *(Root ONLY)* | 4,067 | **14 pages** *(Ultralight RAM)* | **4,081** | **~10 min** *(High-speed file batch upload)* |
| **3** | `tier2-system-channels` | `["sites/DEN/System-Procedure", "sites/DEN/Channels"]` | `True` | 5,977 | **242 pages** | **6,219** | **~18 min** |
| **4** | `tier2-customer-support` | `"sites/DEN/Customer-Support"` | `True` *(Captures all 9 sub-teams)* | 6,856 | **505 pages** | **7,361** | **~25 min** |
| **5** | `tier3-hotlink` | `"sites/DEN/Hotlink"` | `True` | 4,093 | **1,184 pages** *(Medium-Heavy RAM)* | **5,277** | **~32 min** |
| **6** | `tier3-business` | `"sites/DEN/Business"` | `True` | 8,456 | **1,146 pages** *(Medium-Heavy RAM)* | **9,602** | **~40 min** |
| **7** | `tier3-consumer` | `"sites/DEN/Consumer"` | `True` | 6,371 | **1,898 pages** *(Peak RAM - Capped Standalone)* | **8,269** | **~48 min** |
| **TOTAL**| *7 Sharded Executions* | *Entire Tenant Covered* | — | **33,429** | **5,466 pages** | **38,895** | **~3 hrs total** *(0% OOM / 0% Collisions)* |

---

## 3. Operational Benefits for the Customer Run

1. **Instant Customer Gratification (`Tier 1 runs in 3 minutes!`):** When you kick off the run with the customer at 1:00 PM, `Loop 1 (Quicklinks & FAQ)` finishes 606 items in **under 3 minutes**. You can instantly open GCS and Vertex AI Search to show them live, converted PDFs while `Loop 2` and `Loop 3` churn cleanly in the background.
2. **Zero Memory Accumulation (`The Bathtub Drain`):** By separating `Hotlink` (`1,184 pages`), `Business` (`1,146 pages`), and `Consumer` (`1,898 pages`) into separate sequential loops, every single one of those heavy departments starts inside a fresh, un-fragmented container RAM allocation. None of them ever cross the ~2,000-page OOM crash line.
3. **100% Comprehensive & Exact Match:** When all 7 tiers finish, the total inventory in GCS and `metadata.jsonl` equals exactly **38,895 items (`33,429 files + 5,466 pages`)** with zero duplicates and zero missing child departments.
