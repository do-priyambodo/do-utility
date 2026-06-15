#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    import log_helper
except ImportError:
    log_helper = None

# Define ANSI colors for premium styling
COLOR_HEADER = "\033[95m"
COLOR_INFO = "\033[94m"
COLOR_SUCCESS = "\033[92m"
COLOR_WARN = "\033[93m"
COLOR_FAIL = "\033[91m"
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"

def print_header(title):
    print(f"\n{COLOR_BOLD}{COLOR_HEADER}=== {title} ==={COLOR_RESET}")

def print_sub_header(title):
    print(f"\n{COLOR_BOLD}{COLOR_INFO}--- {title} ---{COLOR_RESET}")

def print_result(status, message, details=None):
    if status == "PASSED":
        print(f"  {COLOR_SUCCESS}✅ [PASSED]{COLOR_RESET} {message}")
    elif status == "FAILED":
        print(f"  {COLOR_FAIL}❌ [FAILED]{COLOR_RESET} {message}")
        if details:
            print(f"     {COLOR_WARN}👉 Recommendation: {details}{COLOR_RESET}")
    elif status == "WARN":
        print(f"  {COLOR_WARN}⚠️ [WARNING]{COLOR_RESET} {message}")
        if details:
            print(f"     {COLOR_INFO}ℹ️ Detail: {details}{COLOR_RESET}")
    elif status == "DENIED":
        print(f"  {COLOR_FAIL}🚫 [ACCESS DENIED]{COLOR_RESET} {message}")
        if details:
            print(f"     {COLOR_WARN}👉 Recommendation: {details}{COLOR_RESET}")

def run_gcloud_json(cmd):
    """Runs a gcloud command and returns the parsed JSON output."""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        return json.loads(result.stdout), None
    except subprocess.CalledProcessError as e:
        return None, e.stderr.strip()
    except json.JSONDecodeError:
        return None, "Failed to parse JSON output from gcloud."

def check_api_status(project_id):
    print_header("Step 0: Checking Required GCP APIs")
    required_apis = {
        "run.googleapis.com": "Cloud Run API",
        "secretmanager.googleapis.com": "Secret Manager API",
        "storage.googleapis.com": "Cloud Storage API",
        "cloudscheduler.googleapis.com": "Cloud Scheduler API",
        "artifactregistry.googleapis.com": "Artifact Registry API",
        "cloudbuild.googleapis.com": "Cloud Build API",
        "connectors.googleapis.com": "Integration Connectors API",
        "integrations.googleapis.com": "Application Integration API"
    }

    # Query enabled services
    cmd = [
        "gcloud", "services", "list",
        "--project", project_id,
        "--enabled",
        "--filter", "name:(" + " ".join(required_apis.keys()) + ")",
        "--format", "json"
    ]
    enabled_services, err = run_gcloud_json(cmd)
    if err:
        print_result("DENIED", "Unable to list enabled APIs. Verify you have Service Usage Viewer role.", err)
        return False

    enabled_names = {service["config"]["name"] for service in enabled_services}
    all_passed = True
    for api_id, name in required_apis.items():
        if api_id in enabled_names:
            print_result("PASSED", f"{name} ({api_id}) is enabled.")
        else:
            print_result("FAILED", f"{name} ({api_id}) is disabled.", f"Run: gcloud services enable {api_id} --project={project_id}")
            all_passed = False
    return all_passed

def check_member_has_role(policy, role, member):
    """Helper to verify if a member has a role in a policy json."""
    if not policy or "bindings" not in policy:
        return False
    
    # Strip prefix if it exists to match flexibly
    member_stripped = member
    for prefix in ["user:", "group:", "serviceAccount:"]:
        if member.startswith(prefix):
            member_stripped = member[len(prefix):]
            break
            
    for binding in policy["bindings"]:
        if binding.get("role") == role:
            members = binding.get("members", [])
            
            # 1. Check exact match as specified
            if member in members:
                return True
                
            # 2. Check flexible match without prefix
            for m in members:
                m_stripped = m
                for prefix in ["user:", "group:", "serviceAccount:"]:
                    if m.startswith(prefix):
                        m_stripped = m[len(prefix):]
                        break
                if m_stripped == member_stripped:
                    return True
    return False

def get_recommendation_member(member):
    """Helper to format member with user: or group: prefix if omitted."""
    if member.startswith("user:") or member.startswith("group:") or member.startswith("serviceAccount:"):
        return member
    # If no prefix, guess default to user: unless it has keywords indicating a group
    if "group" in member.lower() or "sso" in member.lower():
        return f"group:{member}"
    return f"user:{member}"

def check_task1_service_agent_impersonation(project_id, project_number, custom_sa, sa_policy):
    print_header("Task 1: GCP Service Agents Impersonation on Custom Service Account")
    if not sa_policy:
        print_result("DENIED", f"Cannot check service account policy for {custom_sa}. Verify your IAM permissions on the SA.", "Requires Service Account Admin or custom role with getIamPolicy.")
        return False

    connectors_agent = f"serviceAccount:service-{project_number}@gcp-sa-connectors.iam.gserviceaccount.com"
    scheduler_agent = f"serviceAccount:service-{project_number}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"
    role = "roles/iam.serviceAccountUser"

    t1_passed = True

    # 1. Connectors Service Agent
    if check_member_has_role(sa_policy, role, connectors_agent):
        print_result("PASSED", f"Connectors Service Agent has Service Account User role on {custom_sa}.")
    else:
        print_result(
            "FAILED",
            f"Connectors Service Agent is NOT bound to roles/iam.serviceAccountUser on {custom_sa}.",
            f"gcloud iam service-accounts add-iam-policy-binding {custom_sa} --member=\"{connectors_agent}\" --role=\"{role}\" --project=\"{project_id}\""
        )
        t1_passed = False

    # 2. Cloud Scheduler Service Agent
    if check_member_has_role(sa_policy, role, scheduler_agent):
        print_result("PASSED", f"Cloud Scheduler Service Agent has Service Account User role on {custom_sa}.")
    else:
        print_result(
            "FAILED",
            f"Cloud Scheduler Service Agent is NOT bound to roles/iam.serviceAccountUser on {custom_sa}.",
            f"gcloud iam service-accounts add-iam-policy-binding {custom_sa} --member=\"{scheduler_agent}\" --role=\"{role}\" --project=\"{project_id}\""
        )
        t1_passed = False

    return t1_passed

def check_task2_developer_setup_permissions(project_id, developer_group, custom_sa, secret_name, project_policy, sa_policy):
    print_header("Task 2: SSO/Developer Accounts Deployment & Setup Permissions")
    t2_passed = True

    # A. Project-level permissions
    print_sub_header("A. Project-Level Developer Roles")
    required_project_roles = [
        "roles/cloudfunctions.developer",
        "roles/run.admin",
        "roles/integrations.integrationAdmin",
        "roles/connectors.admin"
    ]

    rec_member = get_recommendation_member(developer_group)
    
    # Check if user has Owner or Editor role on the project
    is_owner = check_member_has_role(project_policy, "roles/owner", developer_group)
    is_editor = check_member_has_role(project_policy, "roles/editor", developer_group)

    if is_owner:
        print(f"  {COLOR_SUCCESS}✅ [PASSED]{COLOR_RESET} Developer group/user is project OWNER (implicit access to all roles).")
    elif is_editor:
        print(f"  {COLOR_SUCCESS}✅ [PASSED]{COLOR_RESET} Developer group/user is project EDITOR (implicit access to project-level developer roles).")
    elif not project_policy:
        print_result("DENIED", f"Cannot retrieve project IAM policy for {project_id}.", "Ensure you have Project IAM Viewer or custom role with getIamPolicy at project level.")
        t2_passed = False
    else:
        for role in required_project_roles:
            if check_member_has_role(project_policy, role, developer_group):
                print_result("PASSED", f"Developer group/user has {role} at project level.")
            else:
                print_result(
                    "FAILED",
                    f"Developer group/user lacks {role} at project level.",
                    f"gcloud projects add-iam-policy-binding {project_id} --member=\"{rec_member}\" --role=\"{role}\""
                )
                t2_passed = False

    # B. Scoped Secret Manager Admin
    print_sub_header("B. Scoped Secret Manager Admin Role")
    if is_owner:
        print_result("PASSED", f"Developer group/user has Secret Manager Admin on secret '{secret_name}' (Implicitly via project OWNER).")
    else:
        secret_cmd = ["gcloud", "secrets", "get-iam-policy", secret_name, "--project", project_id, "--format", "json"]
        secret_policy, err = run_gcloud_json(secret_cmd)
        if err:
            if "NOT_FOUND" in err or "not found" in err.lower():
                print_result("WARN", f"Secret '{secret_name}' not found.", f"Verify that the secret exists in project '{project_id}'.")
            else:
                print_result("DENIED", f"Cannot retrieve IAM policy for secret '{secret_name}'.", err)
                t2_passed = False
        else:
            role = "roles/secretmanager.admin"
            # Check if granted either at Secret level OR inherited at Project level
            if check_member_has_role(secret_policy, role, developer_group):
                print_result("PASSED", f"Developer group/user has Secret Manager Admin on secret '{secret_name}' (Scoped).")
            elif project_policy and check_member_has_role(project_policy, role, developer_group):
                print_result("PASSED", f"Developer group/user has Secret Manager Admin at Project level (Inherited).")
            else:
                print_result(
                    "FAILED",
                    f"Developer group/user lacks Secret Manager Admin on secret '{secret_name}'.",
                    f"gcloud secrets add-iam-policy-binding {secret_name} --member=\"{rec_member}\" --role=\"{role}\" --project=\"{project_id}\""
                )
                t2_passed = False

    # C. Scoped Service Account User
    print_sub_header("C. Scoped Service Account User Role")
    if is_owner:
        print_result("PASSED", f"Developer group/user has Service Account User on {custom_sa} (Implicitly via project OWNER).")
    elif not sa_policy:
        print_result("DENIED", f"Cannot check service account policy for {custom_sa} to verify developer impersonation.", "Ensure you have permissions to view SA policy.")
        t2_passed = False
    else:
        role = "roles/iam.serviceAccountUser"
        # Check if granted either at Service Account resource level OR inherited at Project level
        if check_member_has_role(sa_policy, role, developer_group):
            print_result("PASSED", f"Developer group/user has Service Account User on {custom_sa} (Scoped).")
        elif project_policy and check_member_has_role(project_policy, role, developer_group):
            print_result("PASSED", f"Developer group/user has Service Account User at Project level (Inherited).")
        else:
            print_result(
                "FAILED",
                f"Developer group/user lacks Service Account User on {custom_sa}.",
                f"gcloud iam service-accounts add-iam-policy-binding {custom_sa} --member=\"{rec_member}\" --role=\"{role}\" --project=\"{project_id}\""
            )
            t2_passed = False

    return t2_passed

def check_task3_custom_sa_runtime_permissions(project_id, location, custom_sa, secret_name, bucket_name, cloud_run_services, project_policy):
    print_header("Task 3: Custom Service Account Runtime Permissions")
    t3_passed = True

    # A. Scoped Cloud Run Invoker
    print_sub_header("A. Scoped Cloud Run Invoker Role")
    for svc in cloud_run_services:
        svc_cmd = ["gcloud", "run", "services", "get-iam-policy", svc, "--region", location, "--project", project_id, "--format", "json"]
        svc_policy, err = run_gcloud_json(svc_cmd)
        if err:
            if "NOT_FOUND" in err or "not found" in err.lower():
                print_result("WARN", f"Cloud Run service '{svc}' not found in region '{location}'.", "Verify that the service is deployed.")
            else:
                print_result("DENIED", f"Cannot retrieve IAM policy for Cloud Run service '{svc}'.", err)
                t3_passed = False
        else:
            role = "roles/run.invoker"
            # Check if granted at Cloud Run service level or inherited at project level
            if check_member_has_role(svc_policy, role, custom_sa):
                print_result("PASSED", f"Custom SA has Cloud Run Invoker on service '{svc}' (Scoped).")
            elif project_policy and check_member_has_role(project_policy, role, custom_sa):
                print_result("PASSED", f"Custom SA has Cloud Run Invoker at Project level (Inherited).")
            else:
                print_result(
                    "FAILED",
                    f"Custom SA lacks Cloud Run Invoker on service '{svc}'.",
                    f"gcloud run services add-iam-policy-binding {svc} --region=\"{location}\" --member=\"serviceAccount:{custom_sa}\" --role=\"{role}\" --project=\"{project_id}\""
                )
                t3_passed = False

    # B. Scoped Secret Accessor
    print_sub_header("B. Scoped Secret Accessor Role")
    secret_cmd = ["gcloud", "secrets", "get-iam-policy", secret_name, "--project", project_id, "--format", "json"]
    secret_policy, err = run_gcloud_json(secret_cmd)
    if err:
        if "NOT_FOUND" in err or "not found" in err.lower():
            print_result("WARN", f"Secret '{secret_name}' not found.", f"Verify that the secret exists in project '{project_id}'.")
        else:
            print_result("DENIED", f"Cannot retrieve IAM policy for secret '{secret_name}'.", err)
            t3_passed = False
    else:
        role = "roles/secretmanager.secretAccessor"
        if check_member_has_role(secret_policy, role, custom_sa):
            print_result("PASSED", f"Custom SA has Secret Accessor on secret '{secret_name}' (Scoped).")
        elif project_policy and check_member_has_role(project_policy, role, custom_sa):
            print_result("PASSED", f"Custom SA has Secret Accessor at Project level (Inherited).")
        else:
            print_result(
                "FAILED",
                f"Custom SA lacks Secret Accessor on secret '{secret_name}'.",
                                f"gcloud secrets add-iam-policy-binding {secret_name} --member=\"serviceAccount:{custom_sa}\" --role=\"{role}\" --project=\"{project_id}\""
            )
            t3_passed = False

    # B.2 Scoped Secret Viewer
    print_sub_header("B.2 Scoped Secret Viewer Role")
    if secret_policy:
        role_viewer = "roles/secretmanager.viewer"
        if check_member_has_role(secret_policy, role_viewer, custom_sa):
            print_result("PASSED", f"Custom SA has Secret Viewer on secret '{secret_name}' (Scoped).")
        elif project_policy and check_member_has_role(project_policy, role_viewer, custom_sa):
            print_result("PASSED", f"Custom SA has Secret Viewer at Project level (Inherited).")
        else:
            print_result(
                "FAILED",
                f"Custom SA lacks Secret Viewer on secret '{secret_name}'.",
                f"gcloud secrets add-iam-policy-binding {secret_name} --member=\"serviceAccount:{custom_sa}\" --role=\"{role_viewer}\" --project=\"{project_id}\""
            )
            t3_passed = False

    # C. Storage Admin (Required for GCS Connector Connection)
    print_sub_header("C. Project-Level Storage Admin Role")
    if project_policy and check_member_has_role(project_policy, "roles/storage.admin", custom_sa):
        print_result("PASSED", "Custom SA has Storage Admin at Project level (Required for GCS Connector).")
    else:
        print_result(
            "FAILED",
            "Custom SA lacks Storage Admin at Project level (Required for GCS Connector).",
            f"gcloud projects add-iam-policy-binding {project_id} --member=\"serviceAccount:{custom_sa}\" --role=\"roles/storage.admin\" --condition=None"
        )
        t3_passed = False

    # D. Connector Viewer & Invoker (Required to invoke GCS & SharePoint connectors in integrations)
    print_sub_header("D. Project-Level Connector Viewer & Invoker Roles")
    if project_policy:
        has_viewer = check_member_has_role(project_policy, "roles/connectors.viewer", custom_sa)
        has_invoker = check_member_has_role(project_policy, "roles/connectors.invoker", custom_sa)
        
        if has_viewer:
            print_result("PASSED", "Custom SA has Connectors Viewer at Project level.")
        else:
            print_result(
                "FAILED",
                "Custom SA lacks Connectors Viewer at Project level (Required for Connection resolution).",
                f"gcloud projects add-iam-policy-binding {project_id} --member=\"serviceAccount:{custom_sa}\" --role=\"roles/connectors.viewer\" --condition=None"
            )
            t3_passed = False
            
        if has_invoker:
            print_result("PASSED", "Custom SA has Connectors Invoker at Project level.")
        else:
            print_result(
                "FAILED",
                "Custom SA lacks Connectors Invoker at Project level (Required to execute Connection operations).",
                f"gcloud projects add-iam-policy-binding {project_id} --member=\"serviceAccount:{custom_sa}\" --role=\"roles/connectors.invoker\" --condition=None"
            )
            t3_passed = False

    return t3_passed

def main():
    if log_helper:
        log_helper.init_logging("setup")
    parser = argparse.ArgumentParser(
        description="Verify IAM permissions and requirements for Maxis SharePoint to GCS Sync Integration.",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    # Try to load defaults from permissions.json or parameters.json
    params_data = {}
    possible_paths = [
        # Check permissions.json first
        os.path.join(os.path.dirname(__file__), "permissions.json"),
        # Fallback to parameters.json
        os.path.join(os.path.dirname(__file__), "parameters.json")
    ]
    
    default_params_path = None
    for p in possible_paths:
        if os.path.exists(p):
            default_params_path = p
            break

    if default_params_path:
        try:
            with open(default_params_path, 'r') as f:
                params_data = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to read configuration file ({default_params_path}): {e}")

    def get_val(key):
        return params_data.get(key.upper()) or params_data.get(key.lower()) or params_data.get(key)

    parser.add_argument(
        "--project-id",
        default=os.environ.get("PROJECT_ID") or get_val("PROJECT_ID") or "",
        help="GCP Project ID (can also be set via PROJECT_ID env var)"
    )
    parser.add_argument(
        "--location",
        default=os.environ.get("LOCATION") or os.environ.get("REGION") or get_val("LOCATION") or "asia-southeast1",
        help="GCP Region/Location (can also be set via LOCATION/REGION env var; default: asia-southeast1)"
    )
    parser.add_argument(
        "--custom-sa",
        default=os.environ.get("CUSTOM_SA") or os.environ.get("SERVICE_ACCOUNT_EMAIL") or get_val("CUSTOM_SA") or get_val("SERVICE_ACCOUNT_NAME"),
        help="Custom Service Account email (can also be set via CUSTOM_SA env var; default: derived from SERVICE_ACCOUNT_NAME/CUSTOM_SA in config file)"
    )
    parser.add_argument(
        "--bucket-name",
        default=os.environ.get("BUCKET_NAME") or os.environ.get("GCS_BUCKET") or get_val("BUCKET_NAME") or "",
        help="GCS sync bucket name (can also be set via BUCKET_NAME env var)"
    )
    parser.add_argument(
        "--secret-name",
        default=os.environ.get("SECRET_NAME") or get_val("SECRET_NAME") or "",
        help="SharePoint Azure Secret name in Secret Manager (can also be set via SECRET_NAME env var)"
    )
    parser.add_argument(
        "--developer-group",
        default=os.environ.get("DEVELOPER_GROUP") or get_val("DEVELOPER_GROUP") or "group:GCPSSO_Developer_Agentassist-Dev@yourorg.com",
        help="Developer SSO Group member string (can also be set via DEVELOPER_GROUP env var; default: group:GCPSSO_Developer_Agentassist-Dev@yourorg.com)"
    )
    parser.add_argument(
        "--cloud-run-services",
        default=os.environ.get("CLOUD_RUN_SERVICES") or get_val("CLOUD_RUN_SERVICES"),
        help="Comma-separated list of Cloud Run services to check (can also be set via CLOUD_RUN_SERVICES env var; default: derived from FUNCTION_NAME plus fallback list)"
    )

    args = parser.parse_args()

    # Post-process parameters
    project_id = args.project_id
    if not project_id:
        # Try to resolve via active gcloud configuration
        cmd = ["gcloud", "config", "get-value", "project"]
        p_id, _ = run_gcloud_json(cmd)
        if isinstance(p_id, str):
            project_id = p_id
        else:
            # Maybe it returns a direct string or list
            try:
                # If command succeeded but json parse failed (gcloud config get-value project returns clean text)
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                project_id = res.stdout.strip()
            except Exception:
                pass
        
        if not project_id:
            print(f"{COLOR_FAIL}Error: Project ID must be specified or set via active gcloud config.{COLOR_RESET}")
            sys.exit(1)

    location = args.location
    bucket_name = args.bucket_name
    secret_name = args.secret_name

    # SA Email resolution
    custom_sa_raw = args.custom_sa or get_val("SERVICE_ACCOUNT_NAME") or get_val("CUSTOM_SA")
    custom_sas = []
    if custom_sa_raw:
        for sa_item in str(custom_sa_raw).split(","):
            sa_item = sa_item.strip()
            if not sa_item:
                continue
            if "@" in sa_item:
                custom_sas.append(sa_item)
            else:
                custom_sas.append(f"{sa_item}@{project_id}.iam.gserviceaccount.com")
    
    if not custom_sas:
        print(f"{COLOR_FAIL}Error: Custom Service Account must be specified or configured in config file.{COLOR_RESET}")
        sys.exit(1)

    # Cloud Run service list
    if args.cloud_run_services:
        cloud_run_services = [s.strip() for s in args.cloud_run_services.split(",")]
    else:
        # Default fallback list
        cloud_run_services = ["yourorg-sharepoint-list-files"]
        fn_name = params_data.get("FUNCTION_NAME", "")
        if fn_name and fn_name not in cloud_run_services:
            cloud_run_services.insert(0, fn_name)

    # Developer SSO Group formatted check
    dev_group = args.developer_group

    # Resolve project number
    print(f"{COLOR_INFO}Resolving GCP Project Number for project '{project_id}'...{COLOR_RESET}")
    proj_num_cmd = ["gcloud", "projects", "describe", project_id, "--format", "value(projectNumber)"]
    try:
        res = subprocess.run(proj_num_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        project_number = res.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"{COLOR_FAIL}Error retrieving project number: {e.stderr.strip()}{COLOR_RESET}")
        sys.exit(1)

    print(f"\n{COLOR_BOLD}=== ENVIRONMENT CONFIGURATION ==={COLOR_RESET}")
    print(f"Project ID:       {COLOR_INFO}{project_id}{COLOR_RESET}")
    print(f"Project Number:   {COLOR_INFO}{project_number}{COLOR_RESET}")
    print(f"Region/Location:  {COLOR_INFO}{location}{COLOR_RESET}")
    print(f"Custom SAs:       {COLOR_INFO}{', '.join(custom_sas)}{COLOR_RESET}")
    print(f"Developer Group/User: {COLOR_INFO}{dev_group}{COLOR_RESET}")
    print(f"Secret Name:      {COLOR_INFO}{secret_name}{COLOR_RESET}")
    print(f"Bucket Name:      {COLOR_INFO}{bucket_name}{COLOR_RESET}")
    print(f"Services Checked: {COLOR_INFO}{', '.join(cloud_run_services)}{COLOR_RESET}")

    # Step 0: API Checklist
    apis_ok = check_api_status(project_id)

    # Pre-fetch shared Project IAM policy
    project_policy, _ = run_gcloud_json(["gcloud", "projects", "get-iam-policy", project_id, "--format", "json"])

    all_sa_ok = True
    for sa in custom_sas:
        print(f"\n{COLOR_BOLD}{COLOR_HEADER}=================================================={COLOR_RESET}")
        print(f"{COLOR_BOLD}{COLOR_HEADER}🔍 RUNNING CHECKS FOR SERVICE ACCOUNT: {sa}{COLOR_RESET}")
        print(f"{COLOR_BOLD}{COLOR_HEADER}=================================================={COLOR_RESET}")
        
        sa_policy, _ = run_gcloud_json(["gcloud", "iam", "service-accounts", "get-iam-policy", sa, "--project", project_id, "--format", "json"])

        # Step 1: Task 1 verification
        t1_ok = check_task1_service_agent_impersonation(project_id, project_number, sa, sa_policy)

        # Step 2: Task 2 verification
        t2_ok = check_task2_developer_setup_permissions(project_id, dev_group, sa, secret_name, project_policy, sa_policy)

        # Step 3: Task 3 verification
        t3_ok = check_task3_custom_sa_runtime_permissions(project_id, location, sa, secret_name, bucket_name, cloud_run_services, project_policy)
        
        if not (t1_ok and t2_ok and t3_ok):
            all_sa_ok = False

    print_header("SUMMARY REPORT")
    all_ok = apis_ok and all_sa_ok
    if all_ok:
        print(f"\n{COLOR_BOLD}{COLOR_SUCCESS}🎉 ALL PRE-REQUIREMENTS & POLICIES ARE SUCCESSFULLY MET AND CONFIGURED!{COLOR_RESET}")
    else:
        print(f"\n{COLOR_BOLD}{COLOR_FAIL}⚠️ SOME PRE-REQUIREMENTS OR POLICIES ARE MISSING OR MISCONFIGURED!{COLOR_RESET}")
        print("Please review the failures and warnings above, run the recommended commands, and retry the check.")

if __name__ == "__main__":
    main()
