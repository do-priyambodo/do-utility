import json
import os
import subprocess
import urllib.request
import urllib.error
import sys
from apply_parameters import apply_params
try:
    import log_helper
except ImportError:
    log_helper = None

def get_auth_token():
    try:
        token = subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode("utf-8").strip()
        return token
    except Exception as e:
        print(f"❌ Failed to get gcloud access token: {e}")
        sys.exit(1)

def get_param_value(param_dict):
    if not isinstance(param_dict, dict):
        return param_dict
    if "value" in param_dict:
        inner = param_dict["value"]
        if isinstance(inner, dict):
            for k in ["stringValue", "booleanValue", "jsonValue", "intValue"]:
                if k in inner:
                    return inner[k]
            return inner
    for k in ["stringValue", "booleanValue", "jsonValue", "intValue"]:
        if k in param_dict:
            return param_dict[k]
    return param_dict

def ui_to_rest_format(ui_json, service_account=None):
    rest_json = ui_json.copy()
    
    keys_to_remove = [
        "name", "createTime", "updateTime", "lastModifierEmail", 
        "state", "status", "originConnectionsInfo", "lockState", 
        "databaseType", "cloudLoggingDetails", "origin", "snapshotNumber",
        "createdFromTemplate"
    ]
    for key in keys_to_remove:
        rest_json.pop(key, None)
        
    if "integrationConfigParameters" in rest_json:
        for item in rest_json["integrationConfigParameters"]:
            item.pop("value", None)
        
    if service_account:
        rest_json["runAsServiceAccount"] = service_account
        
    in_vars = []
    out_vars = []
    if "integrationParameters" in rest_json:
        for p in rest_json["integrationParameters"]:
            key = p.get("key")
            if key.strip("`").startswith("CONFIG_"):
                continue
            io_type = p.get("inputOutputType", "NONE")
            if io_type in ["IN", "IN_OUT"]:
                in_vars.append(key)
            if io_type in ["OUT", "IN_OUT"]:
                out_vars.append(key)
        
    if "integrationParameters" in rest_json:
        new_params = []
        config_keys = set()
        if "integrationConfigParameters" in rest_json:
            for cp in rest_json["integrationConfigParameters"]:
                config_keys.add(cp.get("parameter", {}).get("key"))
                
        for p in rest_json["integrationParameters"]:
            np = p.copy()
            key = np.get("key")
            if key in config_keys or key.strip("`").startswith("CONFIG_"):
                continue
                
            if np.get("inputOutputType") == "NONE":
                np.pop("inputOutputType", None)
            new_params.append(np)
        rest_json["integrationParameters"] = new_params

    if "triggerConfigs" in rest_json:
        new_triggers = []
        for t in rest_json["triggerConfigs"]:
            nt = t.copy()
            nt.pop("position", None)
            if "startTaskId" in nt:
                nt["startTasks"] = [{"taskId": nt["startTaskId"]}]
                nt.pop("startTaskId", None)
                
            if "properties" not in nt or not nt["properties"]:
                trigger_name = nt["triggerId"].split("/")[-1] if "/" in nt["triggerId"] else nt["triggerId"]
                nt["properties"] = {"Trigger name": trigger_name}
                
            if "inputVariables" not in nt or not nt["inputVariables"] or "names" not in nt["inputVariables"]:
                nt["inputVariables"] = {"names": in_vars}
            if "outputVariables" not in nt or not nt["outputVariables"] or "names" not in nt["outputVariables"]:
                nt["outputVariables"] = {"names": out_vars} if out_vars else {}
                
            new_triggers.append(nt)
        rest_json["triggerConfigs"] = new_triggers
        
    injected_params = []
    if "taskConfigs" in rest_json:
        new_tasks = []
        for t in rest_json["taskConfigs"]:
            nt = t.copy()
            nt.pop("position", None)
            # Keep taskExecutionStrategy to allow OR joins (WHEN_ANY_SUCCEED)
            # nt.pop("taskExecutionStrategy", None)
            nt.pop("externalTaskType", None)
            nt.pop("conditionalFailurePolicies", None)
            nt.pop("successPolicy", None)
            
            is_mapper = False
            if nt.get("task") == "DataMappingTask":
                nt["task"] = "JsonnetMapperTask"
                is_mapper = True
                
            if "label" in nt:
                nt["displayName"] = nt["label"]
                nt.pop("label", None)
                
            if "taskNumber" in nt:
                nt["taskId"] = nt["taskNumber"]
                nt.pop("taskNumber", None)
                
            task_id = nt.get("taskId")

            if "nextTasks" in nt:
                new_next = []
                for edge in nt["nextTasks"]:
                    n_edge = edge.copy()
                    if "taskNumber" in n_edge:
                        n_edge["taskId"] = n_edge["taskNumber"]
                        n_edge.pop("taskNumber", None)
                    if "condition" in n_edge and n_edge["condition"] == "true":
                        n_edge.pop("condition", None)
                    new_next.append(n_edge)
                nt["nextTasks"] = new_next
                
            if nt.get("task") == "SubIntegrationForEachLoopTask":
                nt["task"] = "SubWorkflowForEachLoopV2Task"
                raw_params = nt.get("parameters", {})
                
                workflow_val = raw_params.get("subIntegrationName", {}).get("stringValue") if isinstance(raw_params.get("subIntegrationName"), dict) else raw_params.get("subIntegrationName")
                trigger_val = raw_params.get("subIntegrationTriggerId", {}).get("stringValue") if isinstance(raw_params.get("subIntegrationTriggerId"), dict) else raw_params.get("subIntegrationTriggerId")
                mapping_val = raw_params.get("subIntegrationMapCurrentElementTo", {}).get("stringValue") if isinstance(raw_params.get("subIntegrationMapCurrentElementTo"), dict) else raw_params.get("subIntegrationMapCurrentElementTo")
                array_val = raw_params.get("arrayToIterate", {}).get("stringValue") if isinstance(raw_params.get("arrayToIterate"), dict) else raw_params.get("arrayToIterate")
                
                nt["parameters"] = {
                    "workflowName": {
                        "key": "workflowName",
                        "value": {"stringValue": workflow_val}
                    },
                    "triggerId": {
                        "key": "triggerId",
                        "value": {"stringValue": trigger_val}
                    },
                    "iterationElementMapping": {
                        "key": "iterationElementMapping",
                        "value": {"stringValue": mapping_val}
                    },
                    "listToIterate": {
                        "key": "listToIterate",
                        "value": {"stringValue": f"$`{array_val}`$"}
                    },
                    "disableEucPropagation": {
                        "key": "disableEucPropagation",
                        "value": {"booleanValue": False}
                    },
                    "loopMetadata": {
                        "key": "loopMetadata",
                        "value": {
                            "stringArray": {
                                "stringValues": [f"$`Task_{task_id}_loopMetadata`$"]
                            }
                        }
                    }
                }
                
                injected_params.append({
                    "key": f"`Task_{task_id}_loopMetadata`",
                    "dataType": "JSON_VALUE",
                    "displayName": f"`Task_{task_id}_loopMetadata`",
                    "isTransient": True
                })

            if nt.get("task") == "GenericConnectorTask":
                raw_params = nt.get("parameters", {})
                conn_ver = raw_params.get("connectorVersion", raw_params.get("connectionVersion", {}))
                conn_ver_val = get_param_value(conn_ver)
                
                if conn_ver_val and "/locations/global/providers/" in conn_ver_val:
                    parts = conn_ver_val.split("/locations/global/providers/")
                    conn_ver_val = f"projects/{{projectId}}/locations/global/providers/{parts[1]}"
                    
                conn_name = raw_params.get("connectionName", {})
                conn_name_val = get_param_value(conn_name)

                action_name = raw_params.get("actionName", raw_params.get("operationName", {}))
                action_name_val = get_param_value(action_name)

                nt["parameters"] = {
                    "connectionName": {
                        "key": "connectionName",
                        "value": {"stringValue": conn_name_val}
                    },
                    "connectionVersion": {
                        "key": "connectionVersion",
                        "value": {"stringValue": conn_ver_val}
                    },
                    "operation": {
                        "key": "operation",
                        "value": {"stringValue": "EXECUTE_ACTION"}
                    },
                    "actionName": {
                        "key": "actionName",
                        "value": {"stringValue": action_name_val}
                    },
                    "authOverrideEnabled": {
                        "key": "authOverrideEnabled",
                        "value": {"booleanValue": False}
                    },
                    "connectorInputPayload": {
                        "key": "connectorInputPayload",
                        "value": {"stringValue": f"$`Task_{task_id}_connectorInputPayload`$"}
                    },
                    "connectorOutputPayload": {
                        "key": "connectorOutputPayload",
                        "value": {"stringValue": f"$`Task_{task_id}_connectorOutputPayload`$"}
                    }
                }
                injected_params.append({
                    "key": f"`Task_{task_id}_connectorInputPayload`",
                    "dataType": "JSON_VALUE",
                    "displayName": f"`Task_{task_id}_connectorInputPayload`"
                })
                injected_params.append({
                    "key": f"`Task_{task_id}_connectorOutputPayload`",
                    "dataType": "JSON_VALUE",
                    "displayName": f"`Task_{task_id}_connectorOutputPayload`",
                    "isTransient": True
                })
            
            elif "parameters" in nt:
                new_params = {}
                for pk, pv in nt["parameters"].items():
                    target_pk = pk
                    if is_mapper and pk == "mapConfig":
                        target_pk = "template"
                        if isinstance(pv, dict):
                            if "key" in pv:
                                pv["key"] = "template"

                    if isinstance(pv, dict) and "key" not in pv:
                        new_params[target_pk] = {
                            "key": target_pk,
                            "value": pv
                        }
                    else:
                        new_params[target_pk] = pv
                nt["parameters"] = new_params
                
            new_tasks.append(nt)
        rest_json["taskConfigs"] = new_tasks

    if injected_params:
        if "integrationParameters" not in rest_json:
            rest_json["integrationParameters"] = []
        existing_keys = {p["key"] for p in rest_json["integrationParameters"]}
        for param in injected_params:
            if param["key"] not in existing_keys:
                rest_json["integrationParameters"].append(param)
        
    if "errorCatcherConfigs" in rest_json:
        new_catchers = []
        for ec in rest_json["errorCatcherConfigs"]:
            nec = ec.copy()
            nec.pop("position", None)
            nec.pop("errorCatcherNumber", None)
            new_catchers.append(nec)
        rest_json["errorCatcherConfigs"] = new_catchers

    return rest_json

def upload_and_publish(project_id, location, integration_id, file_path, token, service_account=None, params=None):
    print(f"\n🔄 Starting deployment for {integration_id}...")
    
    if not os.path.exists(file_path):
        print(f"❌ Error: File {file_path} does not exist!")
        return None
        
    if params:
        apply_params(file_path, params)

    with open(file_path, "r") as f:
        ui_workflow_data = json.load(f)
        
    rest_workflow_data = ui_to_rest_format(ui_workflow_data, service_account=service_account)
    
    with open(f"{integration_id}_rest_generated.json", "w") as debug_f:
        json.dump(rest_workflow_data, debug_f, indent=2)
    
    payload_bytes = json.dumps(rest_workflow_data).encode("utf-8")
    
    create_url = f"https://{location}-integrations.googleapis.com/v1/projects/{project_id}/locations/{location}/integrations/{integration_id}/versions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    print(f"📤 Creating draft version at {create_url}...")
    req = urllib.request.Request(create_url, data=payload_bytes, headers=headers, method="POST")
    
    try:
        with urllib.request.urlopen(req) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            version_name = resp_data.get("name")
            print(f"✅ Successfully created version: {version_name}")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"❌ HTTP Error during version creation (Code {e.code}): {e.reason}")
        print(f"Error details: {error_body}")
        return None
    except Exception as e:
        print(f"❌ Exception during version creation: {e}")
        return None
        
    version_id = version_name.split("/")[-1]
    
    publish_url = f"https://{location}-integrations.googleapis.com/v1/projects/{project_id}/locations/{location}/integrations/{integration_id}/versions/{version_id}:publish"
    print(f"🚀 Publishing version {version_id} to production...")
    
    req_publish = urllib.request.Request(publish_url, data=b"{}", headers=headers, method="POST")
    
    try:
        with urllib.request.urlopen(req_publish) as resp_pub:
            print(f"🎉 Successfully published {integration_id}!")
            return version_id
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"❌ HTTP Error during publish (Code {e.code}): {e.reason}")
        print(f"Error details: {error_body}")
        return None
    except Exception as e:
        print(f"❌ Exception during publish: {e}")
        return None

def main():
    if log_helper:
        log_helper.init_logging("setup")
    if not os.path.exists('parameters.json'):
        print("❌ Error: parameters.json not found!")
        sys.exit(1)
        
    with open('parameters.json', 'r') as f:
        params = json.load(f)
        
    PROJECT_ID = params.get("CONFIG_ProjectId")
    LOCATION = params.get("CONFIG_Location")
    SERVICE_ACCOUNT = params.get("CONFIG_Service_Account")
    CHILD_INTEGRATION_NAME = params.get("CONFIG_Child_Integration_Name")
    PARENT_INTEGRATION_NAME = params.get("CONFIG_Parent_Integration_Name")
    
    token = get_auth_token()
    
    # Deploy Child worker first
    child_version = upload_and_publish(
        project_id=PROJECT_ID,
        location=LOCATION,
        integration_id=CHILD_INTEGRATION_NAME,
        file_path="child_workflow.json",
        token=token,
        service_account=SERVICE_ACCOUNT,
        params=params
    )
    
    if not child_version:
        print("❌ Child workflow deployment failed. Aborting parent deployment.")
        return
        
    # Deploy Parent orchestrator second
    parent_version = upload_and_publish(
        project_id=PROJECT_ID,
        location=LOCATION,
        integration_id=PARENT_INTEGRATION_NAME,
        file_path="parent_workflow.json",
        token=token,
        service_account=SERVICE_ACCOUNT,
        params=params
    )
    
    if parent_version:
        print("\n🌟 ALL SYNC INTEGRATIONS DEPLOYED AND ACTIVE SUCCESSFULLY!")

if __name__ == "__main__":
    main()
