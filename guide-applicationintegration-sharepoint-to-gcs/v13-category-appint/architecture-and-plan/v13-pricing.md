# 💰 V13 Financial Modeling & Pricing Architecture: Application Integration & Integration Connectors

**Version:** 13.0.0-PROPOSED  
**Date:** 16 July 2026  
**Status:** Authoritative Cost & Financial Model for `V13 / Category AppInt`  
**Target Scenario:** Daily synchronization of **50,000 SharePoint assets** (`Pages + Regular Files`) with a **5% daily change rate** (`2,500 delta assets/day -> 75,000 delta assets/month`).

---

## 1. Application Integration & Integration Connectors Pricing Construct

Google Cloud Application Integration (`AppInt`) and Integration Connectors operate under two primary billing tiers: **Pay-As-You-Go (Consumption-Based)** and **Enterprise Subscription (Tiered Entitlements)**.

### 1.1. Pay-As-You-Go (`Consumption-Based Billing`)
In the Pay-As-You-Go model, you are charged strictly for what you execute and the external connectors you invoke:

1. **Integration Executions (`Parent & Child Workflows`):**
   * **Unit Price:** **`$0.002 per execution`** (`or $2.00 per 1,000 integration executions`).
   * **Definition:** Every time an integration workflow is triggered (`via Cloud Scheduler, API, or Sub-Workflow / Call Integration task`), 1 execution is billed regardless of how many internal tasks (`mappings, conditions, variables`) run inside that workflow.
   * **Sub-Workflow Billing:** If a parent workflow triggers a child workflow (`Call Integration task`) 100 times inside a `For-Each` loop, you are billed for **1 parent execution + 100 child executions = 101 executions (`$0.202`)**.

2. **Integration Connectors (`Managed SharePoint / External Connectors`):**
   * When using managed **Integration Connectors** (`e.g., the official SharePoint Connector`), connections are billed under either:
     * **Node-Hour Billing (`Active Connections`):** A dedicated connection node is charged while active (`approx. $0.40 to $0.50 per node-hour -> ~$292 to $365/month for 24/7 active connections`).
     * **Per-Connector API Call / Data Processed:** Or per connector invocation/payload volume (`approx. $0.0005 per connector API call or per GB processed`).
   * **The REST / HTTP Alternative (`Zero Connector Surcharge`):** If AppInt uses the standard **HTTP Task** or **Call REST Endpoint Task** pointing to a Cloud Run worker (`or raw Graph API with OAuth JWT`), there is **$0.00 Integration Connector node fee and $0.00 per-call surcharge**. You pay ONLY the base AppInt execution rate (`$0.002`).

### 1.2. Enterprise Subscription (`Apigee / Application Integration Packs`)
For large-scale enterprise tenants, organizations purchase pre-allocated monthly execution entitlements (`e.g., Standard or Enterprise Packs providing 5 million to 20+ million executions/month + bundled active connector nodes`). If the monthly execution volume stays within the subscription tier, incremental marginal cost is **`$0.00`**.

---

## 2. Mathematical Cost Modeling: 50,000 Assets with 5% Daily Delta (`2,500 changed assets/day`)

Let's model the exact financial cost of synchronizing **50,000 assets every single day** where **95% of assets (`47,500`) are unchanged** and **5% (`2,500 assets`) are new or modified**.

* **Daily Total Inventory Evaluated:** `50,000 assets` (`1,500,000 item checks / month`).
* **Daily Delta Volume Needing Render / Upload:** `2,500 assets` (`75,000 delta assets / month`).
* **Average Asset Size:** `2 MiB` (`50,000 * 2 MiB = 100 GB total inventory; 2,500 * 2 MiB = 5 GB daily delta throughput -> 150 GB / month`).

---

### 🚨 Model A (The Anti-Pattern): Unbatched, Item-by-Item Child Workflow Executions for ALL 50,000 Assets
If the Application Integration parent discovery workflow iterates over 50,000 items and **fires a separate Child Integration Workflow (`or Call Integration task`) for every single item (`50,000 child executions/day`)** just to check if it changed:

* **Parent Discovery Executions:** `1 execution/day * 30 days = 30 executions/month` -> `30 * $0.002 = $0.06 / month`.
* **Child Executions (`Unbatched 1-to-1`):** `50,000 executions/day * 30 days = 1,500,000 executions/month`.
* **AppInt Execution Cost:** `1,500,000 * $0.002 =` **`$3,000.00 per month ($36,000.00 / year)`**.
* **Financial Assessment:** **UNACCEPTABLE WASTE.** You would be spending **$2,850.00/month** (`47,500 * 30 * $0.002`) purely on paying AppInt $0.002 per item just to check a timestamp and say "Skipped!"

---

### ⚖️ Model B: Unbatched 1-to-1 Child Executions for ONLY the 5% Changed Assets (`Post-Delta Filter`)
If the parent workflow (`or a fast Tier-1 Bulk Pre-Check in Cloud Run / Datastore`) filters out the 47,500 unchanged items in bulk first, and **only triggers a Child Integration Workflow for the 2,500 changed assets (`1 child execution per changed asset`)**:

* **Parent Discovery & Delta Pre-Check Executions:** `4 category executions/day * 30 days = 120 executions/month` -> `120 * $0.002 = $0.24 / month`.
* **Child Executions (`Unbatched Delta Only - 2,500/day`):** `2,500 executions/day * 30 days = 75,000 executions/month`.
* **AppInt Execution Cost:** `(120 + 75,000) * $0.002 =` **`$150.24 per month ($1,802.88 / year)`**.
* **Financial Assessment:** **95% Cost Reduction vs Model A.** By making delta skip decisions in bulk before spawning child workflows, monthly execution cost drops from $3,000 down to $150.

---

### 🌟 Model C (The V13 Gold Standard): Micro-Batched Child Executions (`10 to 50 Items per Execution`)
To achieve enterprise cost perfection, V13 batches the **2,500 changed delta assets into micro-batches of 10 or 50 items per Child Workflow / Worker Invocation** (`just like V10's Parent_Files_List batches of 50`):

#### Option C1: Micro-Batch Size = 10 Delta Items per Child Execution
* **Daily Child Executions Required:** `2,500 changed items / 10 = 250 child executions/day`.
* **Monthly Child Executions:** `250 * 30 days = 7,500 executions/month`.
* **AppInt Execution Cost:** `(120 parent + 7,500 child) * $0.002 =` **`$15.24 per month ($182.88 / year)`**.

#### Option C2: Standard Batch Size = 50 Delta Items per Child Execution (`V10 Parity Batching`)
* **Daily Child Executions Required:** `2,500 changed items / 50 = 50 child executions/day`.
* **Monthly Child Executions:** `50 * 30 days = 1,500 executions/month`.
* **AppInt Execution Cost:** `(120 parent + 1,500 child) * $0.002 =` **`$3.24 per month ($38.88 / year)`**.
* **Financial Assessment:** **99.89% Cost Reduction vs Model A.** By combining Tier-1 Delta Pre-Checking with 50-item batches, the entire 50,000-asset daily enterprise sync costs just **`$3.24 per month in AppInt executions`**!

---

## 3. Total Cost of Ownership (`TCO`) Breakdown for V13 (`Model C2: 50-Item Batches`)

Below is the complete, full-stack estimated monthly bill for running the V13 Inverted Architecture against a **50,000 asset / 5% delta (`2,500/day`) workload**:

| Cloud Service / Component | Billing Metric / Volume | Unit Rate | Monthly Cost (USD) |
| :--- | :--- | :--- | :---: |
| **Application Integration (`Parent + Child Workflows`)** | `1,620 total executions/month` (`120 parent + 1,500 child`) | `$0.002 / execution` | **`$3.24`** |
| **Cloud Run Worker (`/v13/render_page & /v13/process_file`)** | `2,500 requests/day * 5s avg * 2 vCPU / 2 GiB RAM` | Standard Cloud Run Tier (`~$0.000024/vCPU-s + $0.0000025/GiB-s`) | **`~$14.50`** |
| **Cloud Storage (`GCS Destination Bucket`)** | `100 GB stored total + 150 GB/month delta writes` | `$0.02 / GB/month storage + $0.05 per 10,000 Class A PUTs` | **`~$2.50`** |
| **Cloud Datastore / Redis (`Tier 1 Delta Hash Lookup Table`)** | `1,500,000 read checks/month + 75,000 write updates/month` | `$0.06 per 100,000 reads + $0.18 per 100,000 writes` | **`~$1.05`** |
| **Microsoft Graph / SharePoint API Egress** | `5 GB/day delta download ingress into GCP` | Free Ingress into GCP (`Upstream M365 egress depends on tenant`) | **`$0.00`** |
| **TOTAL ESTIMATED MONTHLY TCO** | **Full 50,000 Asset Daily Sync Pipeline** | **Enterprise Resilient, 0% OOM, 0% Collisions** | **`~$21.29 / month`** |

---

## 4. Architectural Cost Guardrails for V13 Engineering

To ensure the V13 implementation rigorously protects the customer from accidental cloud billing spikes, all V13 workflows and workers must adhere to **Three Mandatory Cost Guardrails**:

1. **Never Trigger Unbatched Child Integrations on Unchanged Items (`No $3,000 Leaks`):**
   * The AppInt parent workflow must NEVER execute a `Call Integration` child sub-workflow inside a raw 50,000-item discovery loop.
   * **The Rule:** The loop MUST first invoke a lightweight batch check (`POST /v13/check_delta_batch` or Datastore filter) to drop the 95% unchanged items (`47,500/day`) before any child execution or Playwright Chromium instance is spawned.
2. **Enforce Micro-Batching on REST Worker Invocations (`Batch Size >= 10`):**
   * Rather than passing 1 delta item per HTTP request (`75,000 requests/month -> $150 in AppInt fees`), group Delta items into arrays of **10 to 50 items per payload** before calling `/v13/render_page` or `/v13/process_file`.
3. **Prefer OAuth JWT HTTP / REST Tasks over Node-Hour Connectors (Where Applicable):**
   * Unless the customer's enterprise subscription explicitly bundles free/unlimited `Integration Connectors` nodes, use our verified **Service Principal OAuth JWT authentication over standard HTTP / Call REST Endpoint tasks** to maintain **$0.00 connector node-hour overhead** and keep the total monthly pipeline operating cost under **$25.00/month**.
