---
title: Data and Privacy Policy
doc_type: policy
tier: all
---

## How Nimbus protects customer data

Nimbus stores customer files, comments, activity logs and account details on behalf of the customer. The customer owns their data, and Nimbus processes it only to provide the Nimbus service. Nimbus does not sell customer data and does not use customer file contents to train machine-learning models. Nimbus staff can access customer files only when the customer grants access for a support request, or when required by law.

## Encryption

All Nimbus customer data is encrypted in transit and at rest. Data in transit between Nimbus users and Nimbus servers is protected with TLS 1.2 or higher. Data at rest, including files, file versions, backups and database records, is encrypted with AES-256. Encryption keys are managed in a dedicated key management service and rotated every year. Encryption applies to every plan, including the Free plan, and cannot be turned off.

## Data residency

Nimbus stores customer data in one of two regions: the United States (US) or the European Union (EU). The region determines where files, backups and activity logs are stored. Data stays in the chosen region; it is not copied to the other region for storage or backup.

## Data residency on the Free plan {tier=free}

Free plan workspaces are assigned a data region automatically when the workspace is created, based on the country of the workspace owner: owners in the EU, EEA, UK and Switzerland are placed in the EU region, and all other owners are placed in the US region. Free plan workspaces cannot choose or change their data region.

## Data residency on the Pro plan {tier=pro}

Pro plan workspaces are assigned a data region automatically when the workspace is created, using the same rule as the Free plan: owners in the EU, EEA, UK and Switzerland are placed in the EU region, and all other owners are placed in the US region. Pro plan workspaces cannot choose or change their data region; customers who need to choose a region can upgrade to the Enterprise plan through a support ticket.

## Data residency on the Enterprise plan {tier=enterprise}

Enterprise plan customers can choose whether their workspace data is stored in the US region or the EU region. The Enterprise data region is set during onboarding and recorded in the contract. An Enterprise customer who wants to move an existing workspace to the other region should contact their customer success manager; region moves are scheduled in advance and the workspace is read-only for the duration of the move.

## GDPR and data-subject requests

Nimbus complies with the EU General Data Protection Regulation (GDPR) and the UK GDPR. Individuals can make data-subject requests, including requests to access, correct, delete, restrict or export their personal data. Nimbus responds to data-subject requests within 30 days of receiving a verified request. Requests about personal data inside a customer's workspace are passed to the workspace owner, because the customer, not Nimbus, controls that data. Data-subject requests can be made through a support ticket. Enterprise customers can sign the Nimbus data processing agreement (DPA) as part of their contract; Pro customers can accept the standard DPA from the workspace admin settings.

## Data export

Data export is available on every Nimbus plan, including Free. Workspace owners and admins can export files and the workspace activity log at any time. An export contains a ZIP archive of original files and a CSV file of the activity log. Free plan exports are limited to 2 GB per export request. Full steps, file formats and size limits are covered in the data export troubleshooting guide.

## Data retention after cancellation

When a Nimbus workspace is cancelled or deleted, its data is kept for 30 days. During the 30-day retention period the workspace owner can sign in to export data or reactivate the workspace. After the 30-day retention period, all workspace data, including files, version history and activity logs, is permanently deleted. Encrypted backups containing the data are overwritten during normal backup rotation and are not restored for deleted workspaces.

## Subprocessors and security reports

Nimbus uses a small number of subprocessors for cloud hosting, email delivery and payment processing. The current subprocessor list is available on request through a support ticket. Nimbus is audited annually against SOC 2 Type II; Enterprise customers can request the latest SOC 2 report from their customer success manager under a non-disclosure agreement.

## Reporting a security concern

Customers who believe their account or data has been accessed without permission should change their password, sign out of all sessions from the account security settings, and contact support straight away. Enterprise customers should report suspected security incidents by phone as a severity 1 issue.
