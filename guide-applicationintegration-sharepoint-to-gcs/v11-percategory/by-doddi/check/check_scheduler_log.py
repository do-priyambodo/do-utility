import os, sys
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path: sys.path.insert(0, ROOT_DIR)
if os.path.join(ROOT_DIR, "util") not in sys.path: sys.path.insert(0, os.path.join(ROOT_DIR, "util"))
try: os.chdir(ROOT_DIR)
except Exception: pass

#!/usr/bin/env python3
import json
import subprocess
import sys
import os

def check_logs(limit=15):
    if not os.path.exists("config-parameters.json"):
        print("❌ Error: config-parameters.json not found!")
        sys.exit(1)
        
    with open("config-parameters.json", "r") as f:
        params = json.load(f)
        
    project_id = params.get("CONFIG_ProjectId")
    base_job = params.get("CONFIG_Scheduler_Job_Name")
    
    if not project_id or not base_job:
        print("❌ Error: CONFIG_ProjectId or CONFIG_Scheduler_Job_Name missing in config-parameters.json!")
        sys.exit(1)
        
    print(f"================================================================")
    print(f"🔍 FETCHING CLOUD SCHEDULER LOGS FOR PROJECT: {project_id}")
    print(f"👉 Matching Job ID Substring: {base_job}")
    print(f"================================================================")
    
    query = f'resource.type="cloud_scheduler_job" AND resource.labels.job_id:"{base_job}"'
    cmd = [
        "gcloud", "logging", "read", query,
        f"--project={project_id}",
        f"--limit={limit}",
        "--order=desc",
        "--format=json"
    ]
    
    try:
        raw_output = subprocess.check_output(cmd).decode("utf-8")
        logs = json.loads(raw_output) if raw_output.strip() else []
    except Exception as e:
        print(f"❌ Failed to query Cloud Logging via gcloud: {e}")
        sys.exit(1)
        
    if not logs:
        print("ℹ️ No Cloud Scheduler execution log entries found matching this job.")
        return
        
    for entry in logs:
        ts = entry.get("timestamp", "")[:19].replace("T", " ")
        sev = entry.get("severity", "INFO")
        job_id = entry.get("resource", {}).get("labels", {}).get("job_id", "")
        
        # Parse payload status
        json_p = entry.get("jsonPayload", {})
        proto_p = entry.get("protoPayload", {})
        text_p = entry.get("textPayload", "")
        
        status_msg = ""
        if isinstance(json_p, dict):
            status_obj = json_p.get("status", {})
            if isinstance(status_obj, dict):
                code = status_obj.get("code", "")
                msg = status_obj.get("message", "")
                status_msg = f"Code {code}: {msg}".strip(" :")
            elif isinstance(status_obj, str):
                status_msg = status_obj
            url = json_p.get("url", "")
            if url:
                status_msg += f" [Target: {url}]"
        elif isinstance(proto_p, dict):
            status_msg = proto_p.get("status", {}).get("message", "")
        if not status_msg and text_p:
            status_msg = text_p
            
        icon = "🟢" if sev in ["INFO", "NOTICE", "DEBUG"] else ("🟡" if sev == "WARNING" else "🔴")
        print(f"{icon} [{ts}] [{sev}] Job: {job_id}")
        if status_msg:
            print(f"   └─ Details: {status_msg}")
        print("-" * 64)
        
    print(f"\n💡 Tip: Pass a number as an argument to view more log entries (e.g. python3 check_scheduler_log.py 50)")

if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 15
    check_logs(lim)
