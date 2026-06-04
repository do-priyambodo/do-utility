import json
import os

def apply_params(json_file, params):
    with open(json_file, 'r') as f:
        data = json.load(f)

    # 1. Update integrationConfigParameters array
    if "integrationConfigParameters" in data:
        for p in data["integrationConfigParameters"]:
            key_clean = p["parameter"]["key"].strip("`")
            if key_clean in params:
                val = params[key_clean]
                p["parameter"]["defaultValue"]["stringValue"] = val
                p["value"]["stringValue"] = val

    # 2. Update integrationParameters array
    if "integrationParameters" in data:
        for p in data["integrationParameters"]:
            key_clean = p["key"].strip("`")
            if key_clean in params:
                val = params[key_clean]
                if p.get("dataType") == "STRING_VALUE":
                    if "defaultValue" not in p:
                        p["defaultValue"] = {}
                    p["defaultValue"]["stringValue"] = val
                elif p.get("dataType") == "JSON_VALUE":
                    if "defaultValue" not in p:
                        p["defaultValue"] = {}
                    if isinstance(val, (dict, list)):
                        p["defaultValue"]["jsonValue"] = json.dumps(val)
                    else:
                        p["defaultValue"]["jsonValue"] = str(val)

    # 3. Update task configs dynamically
    if "taskConfigs" in data:
        for t in data["taskConfigs"]:
            # GenericConnectorTask mapping
            if t.get("task") == "GenericConnectorTask" and "parameters" in t:
                params_block = t["parameters"]
                if t.get("label") in ["Download file sharepoint", "List files in SharePoint"]:
                    if "CONFIG_SharePoint_Connection" in params:
                        params_block["connectionName"]["stringValue"] = params["CONFIG_SharePoint_Connection"]
                elif t.get("label") in ["Upload file gcs", "Upload page gcs"]:
                    if "CONFIG_GCS_Connection" in params:
                        params_block["connectionName"]["stringValue"] = params["CONFIG_GCS_Connection"]
            
            # Subworkflow ForEach Loop mapping (Parent Orchestrator calling Child)
            elif t.get("task") == "SubIntegrationForEachLoopTask" and "parameters" in t:
                params_block = t["parameters"]
                if "CONFIG_Child_Integration_Name" in params:
                    params_block["subIntegrationName"]["stringValue"] = params["CONFIG_Child_Integration_Name"]

    # 4. Update runAsServiceAccount
    if "CONFIG_Service_Account" in params:
        data["runAsServiceAccount"] = params["CONFIG_Service_Account"]

    with open(json_file, 'w') as f:
        json.dump(data, f, indent=2)
