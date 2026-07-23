#!/usr/bin/env python3
"""
Unified Diagnostic Log Inspector for SharePoint to GCS Synchronization (V9.0)
Queries Google Cloud Logging across Cloud Scheduler, Cloud Run/Function,
Application Integration, and GCS with customized local timezone formatting
and customizable start time / duration window.
"""

import argparse
import json
import os
import subprocess
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARAMS_FILE = os.path.join(ROOT_DIR, "parameters.json")


def load_params():
    if not os.path.exists(PARAMS_FILE):
        print(f"❌ Error: parameters.json not found at {PARAMS_FILE}")
        sys.exit(1)
    with open(PARAMS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def run_gcloud_logging(title, query, project_id, limit, tz_str, columns, freshness=None):
    print(f"\n================================================================================")
    print(f"📊 {title}")
    print(f"================================================================================")

    format_str = f"table(timestamp.date('%Y-%m-%d %H:%M:%S %Z', tz={tz_str}):label=TIMESTAMP, {columns})"
    cmd = [
        "gcloud", "logging", "read",
        query,
        f"--project={project_id}",
        f"--limit={limit}",
        "--order=desc",
        f"--format={format_str}"
    ]
    if freshness:
        cmd.append(f"--freshness={freshness}")

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        output = res.stdout.strip()
        if output:
            print(output)
        else:
            print("ℹ️ No log entries found matching filter within specified timeframe.")
        if res.stderr and "ERROR" in res.stderr:
            print(f"⚠️ Warning: {res.stderr.strip()}")
    except Exception as e:
        print(f"❌ Error querying logs: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="V9.0 Unified Diagnostic Log Inspector across all GCP components."
    )
    parser.add_argument(
        "--tz",
        default="LOCAL",
        help="Timezone for formatted timestamps (e.g. LOCAL, Asia/Singapore, Asia/Kuala_Lumpur, UTC)."
    )
    parser.add_argument(
        "--since",
        default=None,
        help="Look back time window duration (e.g. 15m, 1h, 6h, 24h)."
    )
    parser.add_argument(
        "--start-time",
        default=None,
        help="Specific RFC3339 start timestamp (e.g. 2026-07-07T05:00:00Z)."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=15,
        help="Maximum number of log records per component (default: 15)."
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Prompt interactively for timezone and start window."
    )

    args = parser.parse_args()

    tz_str = args.tz
    time_filter = ""
    freshness = None

    if args.interactive or (not args.since and not args.start_time):
        print("================================================================================")
        print("🛠️ V9.0 UNIFIED DIAGNOSTIC LOG INSPECTOR")
        print("================================================================================")
        inp_tz = input(f"Enter target Time Zone (e.g. LOCAL, Asia/Singapore, UTC) [{tz_str}]: ").strip()
        if inp_tz:
            tz_str = inp_tz

        print("\nSelect log timeframe filter:")
        print("  1) Relative lookback duration (e.g. 30m, 1h, 6h, 24h)")
        print("  2) Specific start timestamp (RFC3339, e.g. 2026-07-07T05:00:00Z)")
        choice = input("Enter choice [1 or 2, default: 1]: ").strip()
        if choice == "2":
            inp_start = input("Enter RFC3339 start timestamp: ").strip()
            if inp_start:
                time_filter = f' AND timestamp>="{inp_start}"'
        else:
            inp_since = input("Enter lookback duration (e.g. 15m, 1h, 24h) [default: 1h]: ").strip()
            freshness = inp_since if inp_since else "1h"
    else:
        if args.start_time:
            time_filter = f' AND timestamp>="{args.start_time}"'
        elif args.since:
            freshness = args.since

    params = load_params()
    project_id = params.get("CONFIG_ProjectId", "")
    function_name = params.get("CONFIG_CloudFunction_Name", "yourorg-sharepoint-list-files")
    scheduler_job = params.get("CONFIG_Scheduler_Job_Name", "yourorg-sharepoint-sync-hourly")
    gcs_bucket = params.get("CONFIG_GCS_Bucket", "")

    print(f"\n🔍 Target GCP Project: {project_id}")
    print(f"🕒 Display Timezone  : {tz_str}")
    time_desc = f"timestamp >= {args.start_time}" if time_filter else f"Last {freshness}"
    print(f"⏳ Time Filter       : {time_desc}")

    # 1. Cloud Scheduler Logs
    q_sched = f'resource.type="cloud_scheduler_job" AND resource.labels.job_id:"{scheduler_job}"{time_filter}'
    run_gcloud_logging(
        f"CLOUD SCHEDULER JOB ({scheduler_job})",
        q_sched,
        project_id,
        args.limit,
        tz_str,
        "severity, jsonPayload.status.message",
        freshness
    )

    # 2. Traversal Cloud Function / Cloud Run Logs
    q_fn = f'(resource.type="cloud_run_job" OR resource.type="cloud_function" OR resource.type="cloud_run_revision") AND (resource.labels.job_name:"{function_name}" OR resource.labels.service_name:"{function_name}" OR resource.labels.function_name:"{function_name}") AND NOT textPayload=~"ktd|watcher.go|saferun.go|krsieventreader.go|ktdclient.go|goroutine"{time_filter}'
    run_gcloud_logging(
        f"TRAVERSAL CLOUD FUNCTION STREAM ({function_name})",
        q_fn,
        project_id,
        args.limit,
        tz_str,
        "severity, textPayload, jsonPayload.message",
        freshness
    )

    # 3. GCS Bucket Access / Storage Events
    if gcs_bucket:
        q_gcs = f'resource.type="gcs_bucket" AND resource.labels.bucket_name:"{gcs_bucket}"{time_filter}'
        run_gcloud_logging(
            f"GCS BUCKET EVENTS (gs://{gcs_bucket})",
            q_gcs,
            project_id,
            args.limit,
            tz_str,
            "severity, protoPayload.status.message, protoPayload.authenticationInfo.principalEmail",
            freshness
        )

    print("\n================================================================================")
    print("✅ Diagnostic Log Inspection Complete.")
    print("================================================================================\n")


if __name__ == "__main__":
    main()
