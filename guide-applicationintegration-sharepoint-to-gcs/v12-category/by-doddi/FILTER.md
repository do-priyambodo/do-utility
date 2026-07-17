# Guide: SharePoint Filtering Strategy for Active Files & Pages

This document outlines the standard methodologies, Microsoft Graph properties, and logical rules used to restrict SharePoint synchronization to **active, published content**, filtering out drafts, templates, checked-out documents, and manual archives.

---

## 1. Overview & Objective
In large enterprise SharePoint environments (e.g., Maxis DEN Portal), a significant percentage of files and pages consist of obsolete archives, draft versions, or page templates. 

Filtering these out achieves:
1. **Higher Relevance**: Vertex AI Search / Agent Assist indexes only true, active production material.
2. **Reduced Sync Footprint**: Saves network bandwidth, container memory, and GCS storage costs.
3. **API Safety**: Reduces the number of requests sent to the Microsoft Graph API, preventing rate throttling (HTTP 429).

---

## 2. Strategy for Regular Files (Document Libraries)

### A. Manual Archive / Temp Path Filtering
Users frequently organize old or temporary files into manually named folders. 
* **Filter Rule**: Exclude files if their relative path or URL contains any of the configured ignore keywords.
* **Common Keywords**: `/Archive/`, `/Obsolete/`, `/Temp/`, `/Backup/`, `/Drafts/`, `/History/`.
* **Example**: Skip `sites/DEN/Shared Documents/Finance/Archive/Invoice_2019.xlsx`.

### B. Microsoft Graph API Publication Level Facet
Microsoft Graph API returns a `publication` facet for files within drive items.
* **Property**: `driveItem.publication`
* **Values**:
  * `"published"`: The item is a published major version. **(Keep)**
  * `"draft"`: The item is currently a draft (minor version). **(Skip)**
  * `"checkout"`: The item is checked out and locked for editing. **(Skip)**
* **Filter Logic**:
  ```python
  publication = item.get("publication", {})
  if publication.get("level") != "published":
      # Skip draft or checked-out files
      continue
  ```

### C. Checked-Out Status
Files checked out by editors cannot be updated by other users.
* **Property**: `driveItem.publication.level == "checkout"` or presence of `driveItem.checkoutUser`.
* **Filter Logic**: Skip files where `checkoutUser` metadata is present.

---

## 3. Strategy for Modern Site Pages (Site Pages Library)

Modern SharePoint pages (aspx canvas pages) require separate filtering rules:

### A. Exclude Page Templates (Mandatory)
SharePoint reserves a special hidden folder inside `Site Pages` to store layout templates:
* **Excluded Path**: `/SitePages/Templates/`
* **Filter Rule**: Always skip any page where the URL contains `/sitepages/templates/`.

### B. PromotedState Filtering (Pages vs Draft News)
SharePoint classifies modern pages and news posts using the `PromotedState` field:
* **`0`**: Standard content page (Home, Department portals, Wiki pages). **(Keep)**
* **`1`**: Draft news article. **(Skip)**
* **`2`**: Published news article. **(Keep)**
* **Filter Logic**: Exclude any page where `PromotedState == 1`.

### C. Major Version Validation
Site pages support minor draft versions (e.g., `0.2` or `2.1`).
* **Property**: `OData__UIVersionString`
* **Filter Rule**: Only process pages where version ends with `.0` (e.g., `1.0`, `3.0`). This guarantees the page is published and active.

---

## 4. Proposed Parameter-Driven Configuration Design

To support this configuration dynamically without modifying the Python core code, we can define parameters inside parameters.json:

```json
{
  "CONFIG_Filter_Active_Only": true,
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

### High-Level Traversal Logic Integration (Concept):
```python
def should_sync_item(item, is_page=False):
    # 1. Path keyword checks (Files & Pages)
    url_lower = item.get("webUrl", "").lower()
    ignore_keywords = params.get("CONFIG_Ignore_Path_Keywords", [])
    if any(kw in url_lower for kw in ignore_keywords):
        return False
        
    if is_page:
        # 2. Pages specific checks
        if "/sitepages/templates/" in url_lower:
            return False
        if item.get("PromotedState") == 1:
            return False
        version = item.get("OData__UIVersionString", "")
        if version and not version.endswith(".0"):
            return False
    else:
        # 3. Files specific checks
        publication = item.get("publication", {})
        if publication and publication.get("level") != "published":
            return False
            
    return True
```
