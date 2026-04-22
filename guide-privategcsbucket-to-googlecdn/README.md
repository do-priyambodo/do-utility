# How-To: Expose Private GCS Bucket to Google Cloud CDN

This directory contains documentation and configuration for setting up Google Cloud CDN to serve content from a private Cloud Storage (GCS) bucket using AWS Signature Version 4 for authentication.

## Overview
This workaround solves the limitation where Cloud CDN typically requires public buckets or Signed URLs. By leveraging GCS Interoperability (HMAC keys), we can securely expose private bucket content through a Load Balancer with CDN enabled.

## Contents

*   **[CONSOLE.md](./CONSOLE.md)**: Step-by-step instructions to configure the setup manually via the Google Cloud Console.
*   **[TERRAFORM.md](./TERRAFORM.md)**: Instructions and explanation for the automated setup using Terraform.
*   **[terraform/](./terraform/)**: The directory containing the actual Terraform configuration files (`main.tf`, `variables.tf`, etc.).

## Prerequisites
Before you begin, ensure you have:
*   A Google Cloud Project.
*   Appropriate IAM permissions to create Load Balancers, Service Accounts, and HMAC keys.
*   Terraform installed (if using the automated approach).

## Quick Start
Choose one of the following approaches:
1.  **Manual**: Follow the guide in `CONSOLE.md`.
2.  **Automated**: Navigate to the `terraform` directory and follow the instructions in `TERRAFORM.md`.
