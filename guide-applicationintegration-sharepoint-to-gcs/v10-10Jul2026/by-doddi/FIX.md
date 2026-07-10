# 🛠️ Manifest & Datastore Import Quick Fix Guide (`FIX.md`)

This runbook explains how to resolve document import errors in **Vertex AI Discovery Engine / Datastore** without re-running the SharePoint synchronization or re-downloading any files.

---

## 1. Symptom / Error Message

When triggering an import into Vertex AI Discovery Engine (`importDocuments`) via Console or API, you may observe:
- **Status:** `Import completed with issues`
- **Error Sample:**
  ```text
  The provided GCS URI has invalid unstructured data format. Please provide a valid GCS path in either NDJSON(.ndjson) or JSON Lines(.jsonl) format.
  ```
- **Result:** Documents fail to index into Datastore.

---

## 2. Root Cause

When importing unstructured documents into Vertex AI Datastore using a metadata manifest (`gs://<bucket_name>/config/metadata.jsonl`), each line contains:
```json
{
  "id": "Document_ID",
  "structData": {
    "title": "Document.pdf",
    "relative_path": "files/Document.pdf"
  },
  "content": {
    "mimeType": "application/pdf",
    "uri": "gs://<bucket_name>/files/Document.pdf"
  }
}
```

In earlier deployments, the manifest generator wrote document file URIs **without the `files/` folder prefix** (e.g., `gs://<bucket_name>/Document.pdf`).
Because document files are physically stored inside the `files/` directory in Google Cloud Storage (`gs://<bucket_name>/files/...`), Vertex AI Datastore received a **HTTP 404 Not Found** when trying to read `gs://<bucket_name>/Document.pdf` and marked the import as failed.

---

## 3. Instant Standalone Solution (No Re-Sync Needed!)

You **do not** need to re-run the SharePoint to GCS pipeline or ask the customer to re-download files.

We have provided a standalone repair utility: **[`sync/fix_metadata_jsonl.py`](file:///usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v9.0-06Jul2026/by-doddi/sync/fix_metadata_jsonl.py)**.

### Step-by-Step Fix Instructions:

1. Ensure your terminal is in the project directory:
   ```bash
   cd /usr/local/google/home/priyambodo/Coding/DO-PRIYAMBODO/do-CUSTOMERS/customer-maxis/do-applicationintegration/app/v9.0-06Jul2026/by-doddi
   ```

2. Run the instant manifest repair script:
   ```bash
   python3 sync/fix_metadata_jsonl.py
   ```

### What `fix_metadata_jsonl.py` does automatically:
- **Downloads** existing `gs://<CONFIG_GCS_Bucket>/config/metadata.jsonl` from GCS.
- **Inspects** every record and prepends `files/` to any document URI that is missing the folder prefix (`gs://<bucket>/files/<filename>`).
- **Re-uploads** the corrected manifest back to GCS instantly in **< 2 seconds**.

---

## 4. Expected Terminal Output

```text
================================================================================
🛠️ INSTANT GCS MANIFEST FIXER (config/metadata.jsonl)
================================================================================
📂 Step 1: Downloading existing manifest from gs://doddi-bucket-sharepoint-sync/config/metadata.jsonl...
   🟢 Loaded 18 existing records.
⚡ Step 2: Repairing document URIs and relative paths...
   🔧 Corrected 8 document URI(s) to include 'files/' folder prefix.
📤 Step 3: Re-uploading corrected manifest back to GCS...
✅ Successfully updated gs://doddi-bucket-sharepoint-sync/config/metadata.jsonl!
================================================================================
🎉 MANIFEST REPAIR COMPLETE! You can now run Vertex AI Datastore import cleanly.
================================================================================
```

---

## 5. Verifying the Fix

After running `fix_metadata_jsonl.py`, trigger the Datastore import:

```bash
python3 sync/sync_datastore.py
```

The import will read the repaired `config/metadata.jsonl` and successfully index 100% of the documents into your Vertex AI Discovery Engine Datastore.

> [!NOTE]
> **Understanding the Console Activity Log:**
> In the Google Cloud Console (**Vertex AI Search > Data Stores > Activity** tab), past failed import operations remain listed in chronological history. Seeing older failed entries is normal; check the **topmost row** (most recent timestamp) to verify that your new import operation completed with status **Succeeded**, or check the **Documents** tab to view your indexed files.

---

## 6. Permanent Prevention for Future Traversal Runs

Our latest release of `cf-sharepoint/main.py` has been updated so that any future scheduled or manual run of the Cloud Function automatically formats document URIs with `files/` during manifest generation.

---

## 7. FAQ: Should I Purge the Datastore First?

**Q: Do I need to purge or empty the Datastore before running `python3 sync/sync_datastore.py`?**

**A: No, purging is NOT required.**
Because our pipeline uses `reconciliationMode: INCREMENTAL`, running `sync_datastore.py` safely updates existing documents and inserts any new or repaired ones without creating duplicates.

### What if my customer wants a 100% fresh start?
If your customer prefers to clear out any old or experimental index entries so the Datastore matches GCS exactly:

1. **Recommended Approach (FULL Reconciliation Mode - No Manual Purge Required):**
   You can run a FULL reconciliation import, which tells Vertex AI Datastore to synchronize its index so it matches `config/metadata.jsonl` 1-to-1 (automatically removing any documents not present in the manifest). To do this, temporarily set `"CONFIG_Datastore_Reconciliation_Mode": "FULL"` in `parameters.json` and run `python3 sync/sync_datastore.py`.

2. **Manual Purge via Console (If customer wants to empty it manually):**
   Go to Google Cloud Console > **Vertex AI Search** > **Data Stores** > select your Datastore > **Documents** tab, and click **Purge Documents** (or delete documents) before re-running `python3 sync/sync_datastore.py`.

---

## 8. Troubleshooting: `content config of data store must be CONTENT_REQUIRED`

**Symptom:**
When importing documents into a newly created Data Store, you see:
```text
To create document with content, the content config of data store must be CONTENT_REQUIRED.
```

**Root Cause:**
When the Data Store was created, an option for structured metadata or website indexing (`NO_CONTENT`) was selected. Because `config/metadata.jsonl` contains file pointers (`"content": {"mimeType": "...", "uri": "gs://..."}`), Vertex AI requires a Data Store configured for unstructured documents (`CONTENT_REQUIRED`).

**Resolution (Zero SharePoint Re-Sync Required):**
In Vertex AI Discovery Engine, `contentConfig` is immutable and cannot be changed after a Data Store is created. However, because all your files are already safely stored in Google Cloud Storage, you can resolve this in ~30 seconds:

1. **Create a New Data Store:**
   Go to Google Cloud Console (**Vertex AI Search / Agent Builder > Data Stores > Create Data Store**):
   * Select **Cloud Storage** as the data source.
   * Under data type, select 👉 **Unstructured documents with metadata** (or **Unstructured documents**). This automatically sets `contentConfig = CONTENT_REQUIRED`.
   * Enter `gs://<CONFIG_GCS_Bucket>/config/metadata.jsonl` and create the Data Store.
2. **Update `parameters.json`:**
   * Replace `"CONFIG_Datastore_Id"` with your newly created Data Store ID.
3. **Delete the Old Misconfigured Data Store:**
   * Go to **Data Stores**, select the old misconfigured Data Store, and click **Delete**.
   * **Important Reassurance:** Deleting a Data Store **only removes search index metadata** in Vertex AI—it **does NOT delete any files** in your Google Cloud Storage bucket! All thousands of files remain safe and untouched in GCS.

You will end up with exactly **1 active, working Data Store** indexing 100% of your customer's files.



