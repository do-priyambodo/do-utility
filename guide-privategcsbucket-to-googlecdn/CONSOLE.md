# Workaround for Cloud CDN Private Bucket Access (Verified Working)

## 1. Overview and Context
This document outlines the verified working configuration for a workaround that allows Cloud CDN to serve content from a private Cloud Storage (GCS) bucket without using Signed URLs or making the bucket public.

This approach uses the AWS Signature Version 4 protocol. Cloud CDN signs requests to GCS using this format, and GCS verifies them using HMAC keys.

> [!NOTE]
> I already implemented this in my Google Cloud environment (private GCS bucket), and can expose it in through load balancer via CDN → **please change my variables below with yours!**

No AWS account or AWS services are required for this workaround. Although it uses the AWS Signature protocol, all authentication keys are generated and managed entirely within Google Cloud.

---

## 2. Prerequisites: Generate HMAC Keys & NEG
*Your Storage Bucket for private access: mine is `cloudcdn_privatebucket_bydoddi`*

Before configuring the Load Balancer, you must prepare the credentials and the endpoint in Google Cloud.

### Step 2.1: Create a Dedicated Service Account & Grant Permissions
1. Go to **IAM & Admin** > **Service Accounts**.
2. Create a new service account named `sa-cloudcdn-privatebucket-bydo`.
3. **Grant Permissions**: Grant this service account the **Storage Object Viewer** (`roles/storage.objectViewer`) role on your bucket `cloudcdn_privatebucket_bydoddi`.

### Step 2.2: Generate the HMAC Key
1. Go to **Cloud Storage** > **Settings** > **Interoperability**.
2. Create a key for the service account created above.
3. **Save the Access Key (Key ID) and Secret Key (Key)**. 
   *   *Your Access ID*: `YOUR_ACCESS_KEY_ID`
   *   *Your Secret Key*: please store this (you can only see this once!)

### Step 2.3: Create an Internet Network Endpoint Group (NEG)
This is required to treat GCS as a custom origin using the specific bucket domain.
1. Go to **Network Services** > **Network Endpoint Groups**.
2. Click **Create Network Endpoint Group**.
3. **Name**: `origin-cloudcdn-privatebucket-bydoddi`.
4. **Network endpoint type**: Select **Internet (FQDN or IP)**.
5. **Default port**: `443`.
6. Add an endpoint with FQDN: *(use your bucket name as subdomain)* **`cloudcdn_privatebucket_bydoddi.storage.googleapis.com`** (Virtual-host style).

---

## 3. Cloud CDN & Load Balancer Configuration
Create the Load Balancer manually to ensure the correct type is used.

### Step 3.1: Start Load Balancer Configuration
1. Go to **Network Services** > **Load Balancing**.
2. Click **Create Load Balancer**.
3. Select **Application Load Balancer (HTTP/S)** and choose **Global external Application Load Balancer** (Do not select Classic).
4. **ALB Name**: `alb-cloudcdn-privatebucket-bydoddi`.

### Step 3.2: Define the Frontend
1. **Frontend Name**: `fes-cloudcdn-privatebucket-bydoddi`.
2. **Protocol**: **HTTP** on port **80** (or HTTPS on 443 if you have a certificate).
3. **IP address**: **Ephemeral** (or reserved static).

### Step 3.3: Configure the Backend (The Workaround)
1. Select **Create a backend service** and name it `bes-cloudcdn-privatebucket-bydoddi`.
2. Set the protocol to **HTTPS**.
3. For **Backend type**, select **Internet network endpoint group**.
4. Select the NEG you created in Step 2.3 (`origin-cloudcdn-privatebucket-bydoddi`).
5. Enable **Cloud CDN** with **Cache static content**.
6. **Host Header Override**: Add a custom request header: **`Host: cloudcdn_privatebucket_bydoddi.storage.googleapis.com`**. *(This is critical for GCS to recognize the bucket, look at the naming of the subdomain!)*.
7. **Private origin authentication**: Check the box for **Authenticate requests to this origin with AWS Signature Version 4** and fill in:
   *   **Key ID**: `YOUR_ACCESS_KEY_ID`
   *   **Key**: (Your Secret Key)
   *   **Key version**: `v1`
   *   **Region**: `us-central1`

---

## 4. Post-Creation Steps & Testing

### Step 4.1: Get Load Balancer IP
*   **Console**: Find the IP in the Load Balancing list.
*   **Gcloud**: `gcloud compute forwarding-rules list --global --filter="name~fes-cloudcdn-privatebucket-bydoddi"`

### Step 4.2: Test URL
Since we used the bucket-specific domain in the NEG, **do not** include the bucket name in the URL path.
*   **Browse URL**: `http://34.102.166.174/doddi-is-speaking-smallsize.jpg`
*   **Or Run**: `curl -I http://34.102.166.174/doddi-is-speaking-smallsize.jpg` and look for `HTTP/1.1 200 OK`.

> [!CAUTION]
> Accessing the bucket directly via the public URL should fail (if it is truly private):
> `https://storage.googleapis.com/cloudcdn_privatebucket_bydoddi/doddi-is-speaking-smallsize.jpg` *(should not be able to open)*
