# Do-Utility

This is a Utility Project used by **Doddi Priyambodo** that he found useful to share with other developers and the community. It contains various guides, scripts, and configurations for Google Cloud and other tools.

## Projects / Contents

### 1. How-To: Expose Private GCS Bucket to Google Cloud CDN
Located in the [guide-privategcsbucket-to-googlecdn](./guide-privategcsbucket-to-googlecdn) directory.

This project provides a verified workaround to serve content from a private Cloud Storage bucket via Cloud CDN without using Signed URLs or making the bucket public. It includes:
*   Manual setup instructions via Console.
*   Automated setup using Terraform.

### 2. How-To: Deploy SharePoint Integration Connector via CLI & REST API
Located in the [guide-integrationconnector-sharepoint-to-gcs](./guide-integrationconnector-sharepoint-to-gcs) directory.

This guide details a step-by-step workaround to deploy a Google Cloud Integration Connector for Microsoft SharePoint when user accounts have restricted project IAM permissions (lacking role-binding capabilities). Includes:
* CLI pre-flight diagnostic checks.
* Direct REST API provisioning scripts.
* Interactive browser-consent flow guidance.

### 3. How-To: SharePoint-to-GCS Serverless Synchronization Pipeline
Located in the [guide-applicationintegration-sharepoint-to-gcs](./guide-applicationintegration-sharepoint-to-gcs) directory.

A complete production-ready playbook to deploy a serverless, scheduled hybrid sync pipeline from SharePoint to Google Cloud Storage. It utilizes:
* **Python Cloud Function**: Recursively traverses nested SharePoint directories and pre-renders canvas pages to static HTML.
* **Google Application Integration**: Parent-child orchestration workflows to fetch and stream documents to GCS.
* **Cloud Scheduler**: Fully automated headless invocation configuration.

---

*More utilities and guides will be added in the future.*
