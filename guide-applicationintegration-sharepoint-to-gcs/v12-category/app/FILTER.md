# 🎯 SharePoint Asset Filtering & Inventory Reconciliation Guide

## 📌 Executive Summary

During full-tenant SharePoint crawling, the raw discovery scan detects **~38,823 total items**, whereas the production sync pipeline processes **~11,419 curated assets**.

This document outlines the **filtering rules**, **inventory reconciliation logic**, **built-in vs. parameter configurations**, and **image handling policies** implemented in the SharePoint-to-GCS discovery engine (`cf-sharepoint/main.py`).

---

## 📊 1. Raw Scan vs. Production Inventory Breakdown

| Asset Category | Raw Pre-Sync Crawl | Filtered Production Manifest (`metadata.jsonl`) | Sync Ratio | Status |
| :--- | :---: | :---: | :---: | :--- |
| 📄 **Modern Site Pages** | **5,411 pages** | **5,465 pages** | **100%+** | **Full Coverage** (Includes dynamically discovered subsite pages) |
| 📁 **Business Documents** | **33,412 files** | **5,954 files** | **17.8%** | **Noise Reduced** (UI graphics, icons & temp files removed) |
| **TOTAL ASSETS** | **38,823 items** | **11,419 items** | **29.4%** | **Curated Production Knowledge Base** |

---

## 🛡️ 2. The 4 Production Filtering Rules

To prevent flooding Google Cloud Storage (GCS) and Vertex AI Datastores with non-document UI noise, temporary lock files, and un-rendered site assets, four filter layers are applied:

```
                  ┌─────────────────────────────────────────┐
                  │      Raw SharePoint Tenant Inventory    │
                  │              (38,823 Assets)            │
                  └────────────────────┬────────────────────┘
                                       │
           ┌───────────────────────────┴───────────────────────────┐
           ▼                                                       ▼
 📁 DOCUMENT FILE TRAVERSAL                               📄 SITE PAGES ENGINE
   [Excludes System Libraries:                              [Dedicated 4-Strategy Engine:
    Site Assets, Style Library,                              Discovers .aspx SitePages,
    Images, Form Templates]                                  Renders to PDF via Playwright]
           │                                                       │
           └───────────────────────────┬───────────────────────────┘
                                       │
                                       ▼
                     ┌───────────────────────────────────┐
                     │ 🔍 PATH & STATUS FILTERING CHECK  │
                     │  - Ignore Path Keywords (JSON)    │
                     │  - Active File Validation (~$)    │
                     │  - Published Version Check (.0)   │
                     └─────────────────┬─────────────────┘
                                       │
                                       ▼
                  ┌─────────────────────────────────────────┐
                  │     Filtered Production Knowledge Base  │
                  │              (11,419 Assets)            │
                  └─────────────────────────────────────────┘
```

### Rule 1: Exclusion of System & UI Asset Libraries (Built-in Code Rule)
Raw scans traverse all 59+ SharePoint libraries, including internal intranet styling folders. The production pipeline explicitly ignores non-document system libraries in `cf-sharepoint/main.py`:
* **Excluded System Libraries**: `Images`, `Images_Staging`, `Site Assets`, `Style Library`, `Form Templates`, `SpotLight`, `BulletinsImages`, `NewLandingPageImages`, `NewBulletinLandingImages`, `Video`, `DEN Audit Logs`, `Translation Packages`, `Site Collection Documents`, `Site Collection Images`, `DEN User Reports`.
* **Reasoning**: Standard Microsoft SharePoint site collections automatically create these folders for website layout graphics, UI buttons, CSS themes, and page headers—not business documents. Hardcoding these standard Microsoft exclusions in code protects your sync out-of-the-box without requiring complex `parameters.json` edits.

### Rule 2: Ignore Path Keyword Exclusions (User-Configurable in `parameters.json`)
Folders matching operational keywords defined in `parameters.json` are skipped across **BOTH Pages and Files**:
* **Ignored Keywords**: `temp`, `history`, `backup`, `archive`, `draft`, `checkout`, `obsolete`.
* **Reasoning**: Prevents ingesting stale working drafts, historical backups, or temporary working folders.

### Rule 3: Active File Validation (`CONFIG_Filter_Active_Files_Only: true`)
* Automatically filters out temporary Microsoft Office lock files (files starting with `~$`), hidden system files (`.DS_Store`, `desktop.ini`), `.tmp`, `.bak`, and duplicate version control artifacts.

### Rule 4: Published Site Pages Validation (`CONFIG_Filter_Published_Pages_Only: true`)
* **Page Layout Templates**: Page canvas templates inside `/sitepages/templates/` are skipped automatically.
* **Draft Versions**: Un-published page drafts (minor version numbers like `0.1`, `1.2`) are skipped. Only major published page versions (ending in `.0`, e.g., `1.0`, `2.0`) are rendered to PDF.

---

## 🔍 3. Does Filtering Affect Pages or Files?

| Filter Layer | Affects Document Files? | Affects SitePages (.aspx)? | Details |
| :--- | :---: | :---: | :--- |
| **System Asset Libraries** | **YES** | **N/A** *(Pages use dedicated engine)* | `Site Assets`, `Images`, `Style Library` skipped for files. Pages are discovered via Microsoft Graph SitePages API. |
| **Path Keywords (`CONFIG_Ignore_Path_Keywords`)** | **YES** | **YES** | Any file OR page URL containing `temp`, `archive`, `backup`, `draft`, `checkout`, `obsolete` is skipped. |
| **Active / Lock Files (`~$`)** | **YES** | **N/A** | Filters out temporary Office lock files and `.tmp` files. |
| **Published Status / Templates** | **N/A** | **YES** | Skips `/sitepages/templates/` and minor draft page versions. |

---

## 🖼️ 4. Image Handling Policy

A common question is whether image files (`.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`) are saved or skipped.

### A. Embedded Images inside SitePages (`.aspx`) → **SAVED IN GCS**
* **Mechanism**: When Playwright Chromium renders a SharePoint page to PDF (`pages/*.pdf`), it fetches all inline images (`<img src="...">`), charts, diagrams, and photos in real time over HTTPS.
* **Result**: All visual graphics embedded on a page are **100% captured and visually baked directly into the rendered PDF** in GCS alongside their text context.

### B. Standalone Image Documents in Document Libraries → **SAVED IN GCS**
* **Mechanism**: If a user uploads a standalone image document (e.g., `architecture_diagram.png` or `floorplan.jpg`) into a standard SharePoint **Document Library** (e.g., `Documents`, `Guides`), it **IS processed and uploaded to GCS** (`files/<category>/...`).
* **Supported Mime Types**: `image/png`, `image/jpeg`, `image/gif`, `image/bmp`, `image/tiff`.

### C. Intranet UI Asset Libraries (`Images/`, `Site Assets/`) → **SKIPPED**
* **Mechanism**: Loose image files inside SharePoint system UI folders (e.g., site icons, UI buttons, page background bullets) are skipped by default.
* **Reasoning**: Syncing ~22,000 loose, uncontextualized UI icons into GCS wastes storage and creates search noise for Vertex AI Datastores without adding knowledge value.

---

## ⚙️ 5. Configuration Reference (`parameters.json`)

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
