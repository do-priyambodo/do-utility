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
  default     = "cloudcdn-privatebucket-cdndoddi"
}
