# 🎯 SharePoint Asset Filtering Guide

This document outlines the **filtering rules** implemented in the SharePoint-to-GCS production discovery engine (`main.py` and `sharepoint_traversal.py`). All inventory reconciliation rules are strictly divided into built-in defaults and user-configurable parameters.

---

## 🔒 1. Default Filters (Built-in / Cannot Be Configured)

These rules are hardcoded into the pipeline to protect your sync out-of-the-box by preventing system noise, UI assets, and internal templates from clogging Google Cloud Storage and Vertex AI Datastores.

### 🚫 Exclusion of System & UI Asset Libraries (Files)
The production pipeline automatically ignores non-document Microsoft system libraries and internal intranet styling folders across all SharePoint sites during standard Document Library crawling:
* **Excluded System Libraries**: `Style Library`, `Form Templates`, `Site Assets`, `SitePages`, `Pages`, `Site Pages`, `Images`, `Images_Staging`, `SpotLight`, `BulletinsImages`, `NewLandingPageImages`, `NewBulletinLandingImages`, `Video`, `DEN Audit Logs`, `Translation Packages`, `Site Collection Documents`, `Site Collection Images`, `DEN User Reports`.
* **Reasoning**: Standard Microsoft SharePoint site collections automatically create these folders for website layout graphics, UI buttons, CSS themes, and page headers—not business documents. 

### 🚫 Page Templates Exclusion (Pages)
* **Canvas Templates**: Page canvas layouts and template structures located inside the `/sitepages/templates/` directory are skipped automatically.

---

## ⚙️ 2. User-Configurable Filters (Via `parameters.json`)

These rules can be toggled on/off or customized depending on your business requirements.

### 🔍 Ignore Path Keyword Exclusions (`CONFIG_Ignore_Path_Keywords`)
Folders or URLs matching operational keywords defined in `parameters.json` are skipped across **BOTH Pages and Files**:
* **Configurable Keywords**: e.g., `temp`, `history`, `backup`, `archive`, `draft`, `checkout`, `obsolete`.
* **Behavior**: If the file URL or page URL contains any of these keywords, the asset is silently skipped and logged in the `skipped_files.txt` or `skipped_pages.txt` audit manifest in GCS.

### 📄 Published Site Pages Validation (`CONFIG_Filter_Published_Pages_Only: true`)
When set to `true`, the pipeline filters out unpublished or draft pages based on two strict metadata checks:
* **Draft News Posts**: Pages with a `PromotedState` equal to `1` (Unpublished News) are skipped.
* **Draft Versions**: Only major published page versions (minor version number ends in `.0`, e.g., `1.0`, `2.0`) are rendered to PDF. Minor unpublished drafts (e.g., `0.1`, `1.2`) are skipped.

### 📁 Active File Validation (`CONFIG_Filter_Active_Files_Only: true`)
When set to `true`, enforces document status filtering for standard files:
* **Behavior**: Skips document files whose SharePoint `publication.Level` is not explicitly set to `"published"`. 
*(Note: Manual pre/post-sync check scripts additionally flag temporary `~$` Office lock files if executed separately).*

### 🌐 Sync Scope Toggles
* **`CONFIG_Sync_SharePoint_Files` (true/false)**: Disables the entire Document Library traversal entirely if set to `false`.
* **`CONFIG_Sync_SharePoint_Pages` (true/false)**: Disables the Site Pages Playwright rendering engine completely if set to `false`.

---

## 📊 3. Does the Filter Affect Pages or Files?

| Filter Layer | Affects Document Files? | Affects SitePages (.aspx)? | Details |
| :--- | :---: | :---: | :--- |
| **System Asset Libraries** | **YES** | **N/A** *(Pages use dedicated engine)* | `Site Assets`, `Images`, etc. Skipped. |
| **Path Keywords** | **YES** | **YES** | Any file OR page URL containing the keyword is skipped. |
| **Page Templates** | **N/A** | **YES** | Skips `/sitepages/templates/` automatically. |
| **Published Status** | **N/A** | **YES** | Skips draft versions and draft news posts. |
| **Active File Level** | **YES** | **N/A** | Skips files whose publication level is not `"published"`. |

---

## 📄 4. Example Configuration (`parameters.json`)

```json
{
  "CONFIG_Sync_SharePoint_Files": true,
  "CONFIG_Sync_SharePoint_Pages": true,
  "CONFIG_Filter_Active_Files_Only": true,
  "CONFIG_Filter_Published_Pages_Only": true,
  "CONFIG_Ignore_Path_Keywords": [
    "temp",
    "history",
    "backup",
    "archive",
    "draft",
    "checkout",
    "obsolete"
  ]
}
```
