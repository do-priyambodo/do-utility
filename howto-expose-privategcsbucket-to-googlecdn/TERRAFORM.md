# Terraform Configuration for Cloud CDN Private Bucket Access

This document provides the Terraform configuration to set up Cloud CDN with a private Cloud Storage bucket as a custom origin, using AWS Signature Version 4 for authentication.

## Prerequisites

Ensure you have the Google Cloud provider configured in your Terraform files.

## Step-by-Step Guide

Follow these steps in the exact order to configure Cloud CDN with a private bucket using Terraform.

### Step 1: Prerequisites (Optional Gcloud or Console)
By default, the Terraform script is configured to create the bucket for you if you set `create_bucket = true` in `terraform.tfvars`.
However, if you prefer to use an existing bucket or create it manually:
1.  **Manual Bucket Creation**:
    *   **Console**: Go to **Cloud Storage** > **Buckets** > **Create**.
    *   **Gcloud**: Run `gcloud storage buckets create gs://cloudcdn-privatebucket-terraform --location=US-CENTRAL1`
2.  **Verify Region**: Ensure the bucket region matches the `region` variable in Step 2.

### Step 2: Create the Terraform Files
Create the following three files in your working directory.

#### 1. `variables.tf`
Define the variables for the configuration.

```terraform
variable "project_id" {
  description = "The GCP project ID"
  type        = string
}

variable "region" {
  description = "The region for the resources"
  type        = string
  default     = "us-central1"
}

variable "prefix" {
  description = "Prefix for resource names"
  type        = string
  default     = "cdndoddi"
}

variable "create_bucket" {
  description = "Whether to create the bucket or use an existing one"
  type        = bool
  default     = true
}

variable "bucket_name" {
  description = "The name of the bucket"
  type        = string
  default     = "cloudcdn-privatebucket-terraform"
}
```

#### 2. `terraform.tfvars`
Provide the values for the variables.

```terraform
project_id    = "work-mylab-machinelearning"
region        = "us-central1"
prefix        = "cdndoddi"
create_bucket = true
bucket_name   = "cloudcdn-privatebucket-terraform"
```

#### 3. `main.tf`
The main Terraform configuration.

```terraform
provider "google" {
  project = var.project_id
  region  = var.region
}

# 1. Create Service Account
resource "google_service_account" "cdn_sa" {
  account_id   = "sa-${var.prefix}-cdn"
  display_name = "Cloud CDN Private Bucket SA"
}

# 1.5 Create Storage Bucket (if create_bucket is true)
resource "google_storage_bucket" "bucket" {
  count    = var.create_bucket ? 1 : 0
  name     = var.bucket_name
  location = var.region
  
  # Enable uniform bucket-level access as required by organization policy
  uniform_bucket_level_access = true
  
  # For testing, allow force destroy to clean up easily
  force_destroy = true
}

# 2. Grant Bucket Permissions
resource "google_storage_bucket_iam_member" "viewer" {
  bucket = var.create_bucket ? google_storage_bucket.bucket[0].name : var.bucket_name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.cdn_sa.email}"
}

# 3. Create HMAC Key
resource "google_storage_hmac_key" "hmac" {
  service_account_email = google_service_account.cdn_sa.email
}

# 4. Create Internet Network Endpoint Group (NEG)
resource "google_compute_global_network_endpoint_group" "internet_neg" {
  name                  = "neg-${var.prefix}-origin"
  network_endpoint_type = "INTERNET_FQDN_PORT"
  default_port          = 443
}

# Add the GCS endpoint to the NEG
resource "google_compute_global_network_endpoint" "endpoint" {
  global_network_endpoint_group = google_compute_global_network_endpoint_group.internet_neg.name
  fqdn                          = "${var.bucket_name}.storage.googleapis.com"
  port                          = 443
}

# 5. Create Backend Service with Cloud CDN and AWS v4 Auth
resource "google_compute_backend_service" "cdn_backend" {
  name                  = "bes-${var.prefix}-cdn"
  protocol              = "HTTPS"
  enable_cdn            = true
  
  custom_request_headers = [
    "Host: ${var.bucket_name}.storage.googleapis.com"
  ]
  
  backend {
    group = google_compute_global_network_endpoint_group.internet_neg.id
  }

  security_settings {
    aws_v4_authentication {
      access_key_id = google_storage_hmac_key.hmac.access_id
      access_key    = google_storage_hmac_key.hmac.secret
      origin_region = var.region # Must match the bucket region in lowercase
    }
  }
}

# 6. Create URL Map
resource "google_compute_url_map" "cdn_url_map" {
  name            = "urlmap-${var.prefix}-cdn"
  default_service = google_compute_backend_service.cdn_backend.id
}

# 7. Create Target HTTP Proxy
resource "google_compute_target_http_proxy" "cdn_http_proxy" {
  name    = "proxy-${var.prefix}-cdn"
  url_map = google_compute_url_map.cdn_url_map.id
}

# 8. Create Global Forwarding Rule
resource "google_compute_global_forwarding_rule" "cdn_forwarding_rule" {
  name       = "fwdrule-${var.prefix}-cdn"
  target     = google_compute_target_http_proxy.cdn_http_proxy.id
  port_range = "80"
}

# Outputs
output "load_balancer_ip" {
  value = google_compute_global_forwarding_rule.cdn_forwarding_rule.ip_address
}
```

### Step 3: Initialize Terraform (Terminal)
Run this command to initialize the working directory and download the Google provider.
```bash
terraform init
```

### Step 4: Plan the Deployment (Terminal)
Run this command to see the execution plan. Verify that resources will be created as expected.
```bash
terraform plan
```

### Step 5: Apply the Deployment (Terminal)
Run this command to apply the changes. Type `yes` when prompted.
```bash
terraform apply
```
*Note: The output will display the `load_balancer_ip`.*

### Step 6: Verification (Console or Curl)
After Terraform completes, you must verify the setup.
1.  **Wait for Propagation**: Load balancers and Cloud CDN can take **up to 15 minutes** to fully propagate and become active.
2.  **Construct Test URL**: `http://34.117.226.30/doddi.jpg` *(Note: Do not include the bucket name in the path, as we used the bucket-specific domain in the NEG).*
3.  **Test with Curl**:
    ```bash
    curl -I http://34.117.226.30/doddi.jpg
    ```
    *   Look for `HTTP 200 OK` and `X-Cache` headers.
4.  **Verify in Console**: Go to **Network Services** > **Load Balancing** to see the new Load Balancer and verify its backend service has Cloud CDN enabled with AWS Signature v4.

---

## Reference and Fallbacks
The Terraform configuration above is the complete solution. However, if you need to reference the manual steps:
*   **Gcloud**: See [GCLOUD.md](file:///usr/local/google/home/priyambodo/Coding/cust-aeon360-privatebucketcloudcdn/GCLOUD.md).
*   **Console**: See [CONSOLE.md](file:///usr/local/google/home/priyambodo/Coding/cust-aeon360-privatebucketcloudcdn/CONSOLE.md).
