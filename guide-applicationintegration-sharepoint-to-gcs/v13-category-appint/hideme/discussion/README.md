# 🧠 Architectural Brainstorming & Discussion: V13 Inverted Orchestrator Pattern (`AppInt as Crawler/Throttler + Cloud Run as Playwright Worker`)

**Date:** 16 July 2026  
**Context:** Brainstorming and technical evaluation for future architecture (`V13 / Category AppInt`).  
**Status:** Discussion & Guidance Reference (`Not yet implemented in V10 or V11 baselines`).

---

## 1. The Colleague / Expert Guidance (`Input Recommendation`)

> **From:** Cloud Architecture / Application Integration Specialist (`priyambodo@google.com` discussion thread)  
> **Subject:** Shifting Architecture for High-Fidelity SharePoint PDF Rendering at Scale  
>
> To answer your question directly: You cannot completely bypass Cloud Run if you need to render dynamic `.aspx` pages to high-fidelity PDFs. Application Integration does not natively support headless browser rendering (like Playwright), and attempting to hold 50,000 heavy Base64 payloads directly in Application Integration memory would likely hit payload limitations.
>
> However, Application Integration is perfectly suited to solve your scaling issues. You should shift the architecture to use both services for what they are best at:
>
> 1. **Application Integration (Orchestrator):** Use AppInt and the native SharePoint Connector to crawl the API, manage the pagination, and handle Microsoft Graph's strict rate limits (`429s`) using its built-in retry, error handling, and For-Each loops.
> 2. **Cloud Run (Worker):** AppInt can act as a throttler, passing just one (or a very small batch) of URLs at a time to your Cloud Run service via a **Call REST Endpoint** task. Cloud Run spins up Playwright, renders the PDF, saves it directly to a Cloud Storage bucket, and signals success back to AppInt.
>
> By letting AppInt orchestrate the pacing, you prevent the **Signal 9 Memory Exhaustion** and IPC pipe leaks you are currently experiencing on the Cloud Run side, while fully respecting upstream rate limits.
>
> ### Documentation References for this Architecture:
> * **SharePoint Connector (AppInt):** https://cloud.google.com/integration-connectors/docs/connectors/sharepoint/configure
> * **Calling Cloud Run (Call REST Endpoint Task):** https://cloud.google.com/application-integration/docs/call-rest-endpoint-task
> * **Batching & Iteration (For Each Loop Task):** https://cloud.google.com/application-integration/docs/configure-for-each-parallel-task

---

## 2. Current Architecture (`V10 / V11 / V12`) vs Proposed Architecture (`V13 Inverted Pattern`)

We have **not yet implemented this inverted pattern in V10 or V11**. Below is a detailed technical comparison between our current implementation and the proposed V13 architecture:

| Responsibility | Our Current V10/V11/V12 Architecture (`Monolithic Crawler + Dispatcher`) | Proposed V13 Architecture (`Inverted / Pure Orchestrator Pattern`) |
| :--- | :--- | :--- |
| **Crawler & Discovery (`Pagination, Folder Traversal`)** | **Cloud Run / Python (`main.py` / `sharepoint_traversal.py`)** does 100% of the Graph API crawling, pagination (`@odata.nextLink`), and folder traversal. | **Application Integration (AppInt)** uses the **Native SharePoint Connector** and `For-Each` loop tasks to crawl and paginate the Graph API. |
| **Rate Limiting (`HTTP 429`) & Pacing** | Managed manually inside Python code (`time.sleep` with exponential backoff on retry headers). | Managed natively by **Application Integration's** built-in retry mechanisms, error catchers, and connector rate-limiters. |
| **Modern Site Pages (`.aspx -> PDF`)** | **Cloud Run** renders the pages (`_strat1–4`) or prepares them right inside the same container memory space that runs the multi-hour discovery crawl. | **Cloud Run** acts purely as a stateless **Playwright Microservice Worker**. AppInt calls Cloud Run (`Call REST Endpoint task`) passing just 1 (or a tiny micro-batch of) page URL(s) at a time. Cloud Run renders the PDF, saves directly to GCS, and returns `200 OK`. |
| **Regular Files (`.pdf, .docx, .png, etc.`)** | **Application Integration** (`doddi-sharepoint-gcs-parent/child`) receives the batched `Parent_Files_List` from Cloud Run and uploads them to GCS. | **Application Integration** handles direct file stream downloads/uploads natively via connectors or dispatches cleanly to workers. |

---

## 3. Technical Assessment: Why This Guidance is Exceptionally Strong (`Pros`)

### ✅ 1. Solves Cloud Run "Monolith Timeout & Memory Exhaustion (`Signal 9`)"
When a single Cloud Run container is tasked with crawling 50,000+ items across deep folder trees while simultaneously firing up heavy Playwright Chromium browser instances inside the exact same memory space, it experiences severe RAM spikes (`Signal 9 OOM`) and potential Chromium IPC pipe leaks under high concurrency. 

By restructuring Cloud Run into a stateless, on-demand **PDF Rendering Microservice Worker**:
* Cloud Run memory can be tightly bounded (`e.g., 2 GB per container instance`).
* Horizontal autoscaling (`min-instances=0, max-instances=100`) handles traffic bursts cleanly.
* The container execution timeout is never at risk because each request only renders 1 (or a small batch of) page(s) taking 5–15 seconds, rather than running a multi-hour discovery loop.

### ✅ 2. True Enterprise Resiliency (`Zero Crawl Collapses`)
In a monolithic crawl, if page #34,102 hangs or crashes Chromium, the entire Python container could crash or restart, forcing the discovery loop to start over from scratch or requiring complex checkpoint recovery.

Under the V13 Inverted Pattern:
* Application Integration paces the loop item-by-item (`or micro-batch by micro-batch`).
* If a single `.aspx` page causes a rendering crash, **only that single REST endpoint invocation fails**.
* AppInt's `For-Each` loop can retry just that specific page 2–3 times, log a targeted dead-letter error if it permanently fails, and cleanly continue with the remaining 49,999 items without disrupting the parent discovery loop.

### ✅ 3. Native Microsoft Graph Throttling (`HTTP 429`) Shield
Microsoft Graph API enforces strict tenant-level concurrency limits (`HTTP 429 Too Many Requests` and `Retry-After` headers). Application Integration's native connector engine and loop controllers handle throttling backoff natively without complex Python sleep/retry threads.

---

## 4. Trade-Offs & Architectural Considerations for V13 Implementation (`Cons / Watch-outs`)

### ⚠️ 1. High-Speed Delta Sync & Cache Checking Complexity
In our current V10/V11 Python code, we perform ultra-fast **in-memory Delta checking** against a live GCS cache (`gcs_cache` via `target_urls.txt`) or Datastore (`sync_datastore.py`). We routinely cross-reference 38,895 target URLs and timestamps in **under 2 seconds**.

Replicating lightning-fast, multi-thousand-item timestamp and hash comparisons inside purely visual Application Integration data mapping tasks or For-Each filters can introduce execution overhead or latency unless paired with a dedicated caching lookup step (`e.g., querying Datastore or a lightweight lookup endpoint before triggering the render task`).

### ⚠️ 2. SharePoint Connector Licensing & Quota Models
The native **Google Cloud Integration Connectors (`SharePoint Connector`)** is a managed enterprise connector service under the Integration Connectors suite. It operates under distinct node-based pricing, throughput limits, and licensing tiers compared to standard raw HTTP REST invocations authenticated via Azure AD OAuth Service Principal JWT tokens (`which our current code utilizes`).

### ⚠️ 3. V11 Option 2 Hash Suffixing Integration
If we adopt the V11 **Option 2 Deterministic Hash Suffixing (`_hash[:8]`)** to prevent file/page name collisions across subfolders and libraries, the AppInt workflow must pass the item's Graph `id` or normalized `webUrl` to the Cloud Run worker so the worker can compute the exact `SHA-256[:8]` suffix before writing `pages/{Subsite}/{Title}_{hash[:8]}.pdf` to GCS.

---

## 5. Summary & Recommended Next Steps for V13
When ready to begin V13 development:
1. **Keep Cloud Run Purely Stateless:** Build a lightweight FastAPI/Flask endpoint inside Cloud Run (`/render_page`) that accepts `{"url": "...", "destination_gcs_path": "..."}`, runs Playwright, uploads directly to GCS, and returns `{status: "SUCCESS"}`.
2. **Build a Prototype AppInt Flow:** Configure an Application Integration workflow that connects to SharePoint, iterates over a small subsite (`e.g., 50 pages`), and invokes the `/render_page` REST endpoint with controlled concurrency.
3. **Benchmark Delta Sync Performance:** Measure how quickly AppInt can filter out unchanged items vs Python in-memory caching to ensure full-tenant delta runs remain under 5–10 minutes.
