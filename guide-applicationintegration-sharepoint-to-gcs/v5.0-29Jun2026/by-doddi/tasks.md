# 🎯 Active Tasks List (28 June 2026)

## Today's Objectives

- [ ] **Task 1: Change SharePoint Page Sync Output from HTML to PDF**
  - Modify the Traversal Cloud Function and/or synchronization logic so that modern SharePoint site pages are fetched/converted and downloaded as `.pdf` files into Google Cloud Storage (GCS) instead of raw `.html` files.

- [ ] **Task 2: Create or Replace Cloud Scheduler for SharePoint Sync**
  - Create or replace the automated Cloud Scheduler job trigger configured to invoke the Traversal Cloud Function and initiate the periodic SharePoint-to-GCS synchronization run.

- [ ] **Task 3: Create or Replace Datastore Sync Execution Function**
  - Create or replace the Cloud Function responsible for triggering/executing the Vertex AI Agent Builder Data Store synchronization (to index newly synced GCS files into the datastore).

---
*Status: List created. Awaiting discussion on implementation planning.*
