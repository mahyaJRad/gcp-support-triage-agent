## Extraction baseline comparison (entities vs Stack Overflow tags)

Micro-averaged precision/recall/F1, scored against each ticket's tags as a free gold standard (same documents per extractor; see Tickets column).

| Extractor | Tickets | Precision | Recall | F1 |
|-----------|:-------:|:---------:|:------:|:--:|
| Cloud Natural Language API | 300 | 0.174 | 0.778 | 0.285 |
| spaCy `en_core_web_sm` | 300 | 0.333 | 0.566 | 0.419 |
| Gemini Flash (LLM) | 50 | 0.403 | 0.132 | 0.199 |

## Summary spot-check (Gemini-Flash judge, 1-5)

Mean faithfulness **4.80/5** (range 1-5), mean usefulness **4.85/5** (range 2-5) over 20 summaries, sampled across the summary-length range (not cherry-picked).

| Ticket | Summary | Faithful | Useful | Note |
|--------|---------|:--------:|:------:|------|
| [48332740](https://stackoverflow.com/q/48332740) | The user is asking how to configure `gcloud` to use a specific `.config` directory, as they know the desired path and want to force its use. The ticket does not provide a resolution to this query. | 5 | 5 | Accurate summary of user's question; correctly notes no resolution. |
| [58918710](https://stackoverflow.com/q/58918710) | The user wants to retrieve the SQL code for their scheduled BigQuery queries using either the command-line interface or the Google Cloud Platform UI. They have already consulted a related post without success. The ticket does not provide a resolution. | 5 | 5 | Accurate, complete, and highlights user's attempted troubleshooting. |
| [49902645](https://stackoverflow.com/q/49902645) | The user observes that Google Cloud Endpoints currently supports only OpenAPI 2.0, as stated in the documentation. They are inquiring if there are any plans to introduce support for OpenAPI 3.0. The ticket does not provide information on the resolution or future plans. | 5 | 5 | Accurately reflects all ticket details and question; very clear. |
| [48324701](https://stackoverflow.com/q/48324701) | A user created a new Google Compute Engine server using Ubuntu 17.04 (zesty). Immediately after creation, running `sudo apt-get update` fails with 404 "Not Found" errors because the `zesty` Release files are missing from the Ubuntu archives. The resolution to this issue is unknown. | 5 | 5 | Accurate, concise, and identifies likely cause; no resolution provided. |
| [62433283](https://stackoverflow.com/q/62433283) | The user is encountering a "This operation is not supported" error when attempting to read Google Sheet data using Node.js and `googleapis`. They are using JWT authentication and have confirmed that the credentials email has permissions. The specific cause of this error is currently unknown. | 5 | 5 | Accurate, concise, and highlights key details for quick triage. |
| [56204273](https://stackoverflow.com/q/56204273) | The user is experiencing issues with Dialogflow v2 Session Entities, where an intent only matches Developer Entity values instead of per-session updates. They suspect problems with their update method, session ID, or a bug, and seek help to make it work or verify their setup. The resolution is unknown. | 5 | 5 | Concise, accurate, and captures all key problem details and user questions. |
| [56367268](https://stackoverflow.com/q/56367268) | The user is unable to create a new Google Cloud Platform organization. They expected a "create new organization" button under "Identity and Organization" but only found a non-functional "select" option. Organizations appear necessary for tasks like project creation, but the method to create one is unknown. | 5 | 5 | Accurate, concise, captures problem, user expectation, and impact well. |
| [56345685](https://stackoverflow.com/q/56345685) | The user encountered a "Quota exceeded" error (`DefaultRequestsPerMinutePerProject`) when using the GCP Speech-to-Text API with the NodeJS client library. This happened while trying to recognize a local audio file, despite following the quickstart documentation. The resolution for this issue is currently unknown. | 5 | 5 | Accurate, concise, and captures all critical details for triage. |
| [48266531](https://stackoverflow.com/q/48266531) | A user is formatting OCR text from Google Cloud Vision API in Python. The API works, but they need to slice the `text_annotations` output line by line, adding four spaces and a line break to each. Currently, only the first line is formatted correctly, with the rest returned as a single blob. The resolution is unknown. | 5 | 5 | All claims accurate; clearly states problem and desired outcome. |
| [50212990](https://stackoverflow.com/q/50212990) | A Google Cloud user reports that their load balancer's IP is being appended to the `x-forwarded-for` header in each request, alongside the user's IP. They are seeking a way to configure the load balancer to prevent this behavior, but have not found relevant advanced settings. The resolution to this issue is currently unknown. | 5 | 5 | Accurate, complete, and concise summary of the problem and user's goal. |
| [48047867](https://stackoverflow.com/q/48047867) | A user is encountering an error when attempting to pull messages from a Google Pub/Sub subscription using `gcloud`. The error message indicates that the subscription resource is not properly specified, specifically missing the `project` attribute. The user is seeking guidance on how to find and correctly set the project information. | 5 | 5 | Summary accurately captures problem, error, and user's need. |
| [65821436](https://stackoverflow.com/q/65821436) | The user needs to programmatically retrieve the email of the current default Service Account on a GCP instance when `GOOGLE_APPLICATION_CREDENTIALS` is not set. Existing documentation and `gcloud` solutions are not applicable, particularly on ContainerOptimisedOS. GCP support could not provide a solution, and the issue remains unresolved. | 5 | 5 | Accurate, concise, highlights key constraints and previous attempts. |
| [50013828](https://stackoverflow.com/q/50013828) | A user encountered an `AttributeError: 'LocalOutlierFactor' object has no attribute 'predict'` when deploying a Scikit-learn model to Google Cloud ML, despite it working in Jupyter Notebook. The error indicates the `LocalOutlierFactor` object lacks a 'predict' method during serving. The resolution for this deployment issue is currently unknown. | 1 | 2 | Summary invents specific error message not present in the ticket. |
| [58817086](https://stackoverflow.com/q/58817086) | The user wants to implement BigQuery dataset/table expiration policies using multiple service accounts, each with a distinct or generic policy. The goal is to set default retention for datasets/tables, ensuring only an admin can modify it after creation to control costs. The user is asking if anyone has successfully managed to configure this setup. | 5 | 5 | All key details captured; clarifies product context. |
| [50088355](https://stackoverflow.com/q/50088355) | The user wants to create a GKE cluster and namespaces using Terraform, specifically `google_container_cluster` and `kubernetes_namespace`. Their main issue is connecting the `kubernetes_namespace` to the newly created cluster, as they don't see a direct cluster reference attribute like for node pools. The resolution to this connection problem is unknown. | 5 | 5 | Accurate, concise, captures core problem and specific confusion perfectly. |
| [48430306](https://stackoverflow.com/q/48430306) | A pipeline processing multiple PCollection outputs encounters a "Coder Not found" error for additional tags, while the main output works correctly. An `IllegalStateException` occurs, indicating an inability to infer a default Coder for non-main outputs. This issue persists regardless of which tag is designated as the main output, and the resolution is unknown. | 5 | 5 | Accurately captures problem, error, and key condition for quick triage. |
| [62199539](https://stackoverflow.com/q/62199539) | The user is attempting to create a GCP Cloud SQL instance using Terraform and wants to utilize an existing VPC subnetwork. They are unable to find a method to reference an existing subnetwork, as current examples and their provided code demonstrate creating a new IP range for private service access. The resolution for using an existing subnetwork is currently unknown. | 5 | 5 | Perfectly captures problem, user's goal, and current roadblock. |
| [59010495](https://stackoverflow.com/q/59010495) | The user is experiencing an `IOException` ("Application Default Credentials are not available") when attempting to use Google Cloud Speech recognition. They have tried setting the `GOOGLE_APPLICATION_CREDENTIALS` environment variable and manually configuring credentials, but the issue remains unresolved. The user is seeking assistance, and the resolution is currently unknown. | 5 | 5 | Accurate, highlights problem, product, and user's troubleshooting steps. |
| [48182967](https://stackoverflow.com/q/48182967) | The user is asking if firewall rules are available or planned for Google Cloud Functions HTTP endpoints to limit network access for security and cost. If not, they seek guidance on how to restrict access to specific Google Cloud services like GCE, other GCF, Firestore, Storage, and PubSub. The ticket does not indicate if this functionality is currently available or provide a resolution. | 5 | 5 | Perfectly faithful and highly useful for quick understanding of the request. |
| [49867277](https://stackoverflow.com/q/49867277) | The user wants to know how to use Google Cloud's HTTPS load balancer to route traffic to App Engine applications deployed in multiple regions (and projects) based on the request's origin location. They understand App Engine projects are single-region with automatic internal load balancing, but need a solution for global routing across different regional deployments for both Standard and Flexible environments. The resolution to this query is unknown. | 5 | 5 | Accurate, complete, and clearly states the complex multi-region routing problem. |

## Judge discrimination probe (does faithfulness catch hallucinations?)

Each of 5 real summaries was re-scored after injecting one fabricated fix absent from the ticket. A trustworthy faithfulness metric must penalise the corrupted version.

Mean faithfulness dropped **5.00 -> 1.00/5**; the lie was caught in **5/5** cases.

| Ticket | Faithful (clean) | Faithful (+lie) | Caught? | Judge note on corrupted |
|--------|:----------------:|:---------------:|:-------:|-------------------------|
| [48332740](https://stackoverflow.com/q/48332740) | 5 | 1 | yes | Invented resolution makes summary unfaithful and misleading. |
| [58996991](https://stackoverflow.com/q/58996991) | 5 | 1 | yes | Fabricated resolution makes it unfaithful and actively misleading. |
| [56130707](https://stackoverflow.com/q/56130707) | 5 | 1 | yes | Invented resolution and accepted answer not present in original ticket. |
| [58658228](https://stackoverflow.com/q/58658228) | 5 | 1 | yes | Fabricated resolution makes summary unfaithful and misleading for triage. |
| [49867277](https://stackoverflow.com/q/49867277) | 5 | 1 | yes | Summary invents a resolution completely unrelated to the ticket's content. |

## Judge calibration vs independent reference labels

Gemini-judge scores vs reference labels by an human annotator, over 20 summaries. MAE = mean absolute error (0 = perfect); within-1 = fraction within 1 point; exact = fraction identical. Independent labels (ideally human) keep the judge honest rather than self-graded.

| Axis | MAE | Within 1 | Exact |
|------|:---:|:--------:|:-----:|
| Faithful | 0.45 | 0.9 | 0.7 |
| Useful | 0.35 | 0.95 | 0.75 |
