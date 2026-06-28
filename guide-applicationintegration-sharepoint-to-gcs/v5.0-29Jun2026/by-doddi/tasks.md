# 🎯 Active Tasks List (28 June 2026)

## Today's Objectives

- [x] **Task 1: Change SharePoint Page Sync Output from HTML to PDF**
  - Modify the Traversal Cloud Function and/or synchronization logic so that modern SharePoint site pages are fetched/converted and downloaded as `.pdf` files into Google Cloud Storage (GCS) instead of raw `.html` files.

- [ ] **Task 2: Create or Replace Cloud Scheduler for SharePoint Sync**
  - Create or replace the automated Cloud Scheduler job trigger configured to invoke the Traversal Cloud Function and initiate the periodic SharePoint-to-GCS synchronization run.

- [ ] **Task 3: Datastore Sync & GKA SharePoint Link Maintenance**
  - *Goal*: Ensure documents indexed into Vertex AI Agent Builder Data Store retain their original live SharePoint web URLs so Generative Knowledge Assist (GKA) opens the SharePoint page instead of the GCS file.
  - **Task 3.1: Generate JSONL Metadata Index during GCS Sync**
    - *Explanation*: Update `cf-source/main.py` or the upload workflow so that during synchronization, a `metadata.jsonl` manifest file is generated in the GCS bucket. Each line in this JSONL maps the uploaded GCS object URI (`gs://bucket/pages/Page.pdf`) to its structured custom metadata, specifically attaching `"sharepoint_url": item["Url"]` and `"title": item["Name"]`.
  - **Task 3.2: Create or Replace Datastore Sync Cloud Function**
    - *Explanation*: Create or replace the Cloud Function responsible for triggering Vertex AI Agent Builder Datastore synchronization. Configure the `ImportDocumentsRequest` API call to import using **JSONL with metadata** pointing to `gs://bucket/metadata.jsonl`. This ensures Vertex AI Search indexes both the file contents and the custom `sharepoint_url` field.
  - **Task 3.3: Configure Agent Assist UI Component (`linkMetadataKey`)**
    - *Explanation*: In the frontend contact center UI configuration (`<agent-assist-ui-modules>` / V2 config in `app.js`), add `articleLinkConfig: { linkMetadataKey: "sharepoint_url", target: "blank" }`. When an agent clicks a reference link on a GKA suggestion card, the UI component will extract `sharepoint_url` from the document metadata and launch the original SharePoint web page in a new tab.

---
*Status: Task 1 completed (Option A Fluent UI PDF). Task breakdown added for GKA SharePoint Link maintenance. Ready for Task 2.*
