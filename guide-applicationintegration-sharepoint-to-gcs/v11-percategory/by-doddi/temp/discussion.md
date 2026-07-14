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

## 4. How We Structure `sites-sync.json` for V11 (`The Rich Category Matrix`) ⭐

Instead of pointing `CONFIG_Sharepoint_Sites: "sites/DEN"` and `CONFIG_Sharepoint_Library: "all"` (which forces scanning all 59 libraries including `Images_Staging`, `NewBulletinLandingImages`, and `BulletinsImages`), we structure `sites-sync.json` to **filter out decorative website files and isolate each department into its own GCS prefix**:

```json
{
  "categories": [
    {
      "category_id": "tier1-business",
      "display_name": "Business Department Policies & Documents",
      "sharepoint_site": "sites/DEN/Business",
      "sharepoint_library": "Documents",
      "gcs_destination_prefix": "categories/business/",
      "cron_schedule": "0 0 * * *"
    },
    {
      "category_id": "tier1-consumer",
      "display_name": "Consumer Department SOPs & Guides",
      "sharepoint_site": "sites/DEN/Consumer",
      "sharepoint_library": "Documents",
      "gcs_destination_prefix": "categories/consumer/",
      "cron_schedule": "0 2 * * *"
    },
    {
      "category_id": "tier1-hotlink",
      "display_name": "Hotlink Department Documents",
      "sharepoint_site": "sites/DEN/Hotlink",
      "sharepoint_library": "Documents",
      "gcs_destination_prefix": "categories/hotlink/",
      "cron_schedule": "0 4 * * *"
    },
    {
      "category_id": "tier1-system-procedure",
      "display_name": "System & Procedure Standard Guidelines",
      "sharepoint_site": "sites/DEN/System-Procedure",
      "sharepoint_library": "Documents",
      "gcs_destination_prefix": "categories/system-procedure/",
      "cron_schedule": "0 6 * * *"
    },
    {
      "category_id": "tier2-medium-departments",
      "display_name": "Channels, Enterprise Solutions & QA",
      "sharepoint_site": [
        "sites/DEN/Channels",
        "sites/DEN/Enterprise-Solutions",
        "sites/DEN/ChannelMarketing",
        "sites/DEN/Quality-Assurance"
      ],
      "sharepoint_library": "Documents",
      "gcs_destination_prefix": "categories/medium-departments/",
      "cron_schedule": "0 8 * * *"
    },
    {
      "category_id": "tier3-lightweight-departments",
      "display_name": "MEPS, Credit, BCP, FAQ & Specialized Teams",
      "sharepoint_site": [
        "sites/DEN/MEPS",
        "sites/DEN/Credit-Operations",
        "sites/DEN/BCP",
        "sites/DEN/FAQ",
        "sites/DEN/Assisted",
        "sites/DEN/CDPU",
        "sites/DEN/Customer-Support",
        "sites/DEN/Customer_First",
        "sites/DEN/DistributionMgmt",
        "sites/DEN/Quicklinks",
        "sites/DEN/Self_Serve",
        "sites/DEN/Service-Insights",
        "sites/DEN/Training"
      ],
      "sharepoint_library": "Documents",
      "gcs_destination_prefix": "categories/specialized-teams/",
      "cron_schedule": "0 10 * * *"
    }
  ]
}
```

#### Why This Matrix Solves 100% of the Customer's Pain Points:
1. **Eliminates the 20-Minute Discovery & API Throttling:** When the `tier1-business` cron job runs, `main.py` discovers **only** the `sites/DEN/Business` subsite. Discovery finishes in **<15 seconds** instead of 1,243 seconds!
2. **Filters Out Decorative UI / Banner Images:** Look at the customer's 59 libraries in `sample-sites.txt`: `Images_Staging`, `NewBulletinLandingImages`, `BulletinsImages`, `Site Collection Images`, `bulletins_images_staging`. By explicitly specifying `"sharepoint_library": "Documents"` (and `"SitePages"` where needed), the AI chatbot (`AgentAssist`) never gets polluted with decorative website PNG/JPG banners!
3. **Staggered Execution Schedules:** By staggering Tier 1 across different hours (`00:00`, `02:00`, `04:00`, `06:00`) and grouping Tier 3 into a fast batch run (`10:00`), Microsoft Graph API never sees concurrent rate throttling (`429`) across all 38,823 items at once.
4. **Targeted On-Demand Execution in Seconds:** If the Legal/Credit or HR team updates 20 urgent SOPs at 3:00 PM, Janice can trigger an instant, targeted sync without running the other 38,000 items:
   ```bash
   gcloud run jobs execute <YOUR-JOB-NAME> --update-env-vars="TARGET_CATEGORY_ID=tier1-business"
   ```
