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
