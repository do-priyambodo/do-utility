# Few-Files-Only Synchronization Test Runner

This directory contains lightweight verification tooling designed to test the Serverless SharePoint-to-GCS synchronization pipeline on a limited subset of items (e.g., 3–5 files) without triggering a full synchronization across thousands of production documents.

---

## Files

*   **[test_few_files.py](test_few_files.py)**: An automated test runner derived from [sync_sharepoint_to_gcs.py](../sync_sharepoint_to_gcs.py). It queries the deployed Cloud Function for the library manifest, slices the items array to `--limit`, and submits the sample subset to Application Integration.

---

## Usage

1. Ensure your deployment parameters are configured in `../config-parameters.json` and that your GCP credentials are active:
   ```bash
   gcloud auth login
   ```
2. Execute the randomized test runner specifying the number of documents and pages to sample (defaults are `2` each):
   ```bash
   python3 test_few_files.py --docs=2 --pages=2
   ```
3. Monitor the live execution progress using the returned Execution UUID:
   ```bash
   python3 ../check_application_integration_execution.py "<PROJECT_ID>" "<LOCATION>" "<PARENT_INTEGRATION_NAME>" "<EXECUTION_ID>"
   ```
