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
