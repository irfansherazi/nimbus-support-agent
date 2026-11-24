---
title: Troubleshooting Integrations and the API
doc_type: troubleshooting
tier: all
---

## Integrations available in Nimbus

Nimbus connects to Slack, Google Drive and Microsoft 365, and offers a REST API and webhooks for custom integrations. Integrations are managed by workspace admins from the admin console under Integrations. Integrations, the API and webhooks are available on the Pro and Enterprise plans.

## Free plan {tier=free}

The Nimbus Free plan does not include API access, webhooks or the Slack, Google Drive and Microsoft 365 integrations. API requests made with a Free plan workspace are refused with an error stating that the plan does not include API access. To use integrations or the API, the workspace must upgrade to the Pro or Enterprise plan; plan upgrades are handled by a specialist through a support ticket.

## Reconnecting an expired connection

Nimbus connects to Slack, Google Drive and Microsoft 365 using OAuth tokens. OAuth tokens can expire or be revoked when the connecting user changes their password, leaves the organisation, or when an admin on the other service removes Nimbus's access. When a token expires, the integration shows the status Disconnected in the admin console and stops syncing. To reconnect an expired OAuth connection:

1. Go to the admin console, then Integrations, and select the disconnected integration.
2. Select Reconnect. You are sent to the other service's sign-in page.
3. Sign in with an account that has admin rights on the other service, and approve the permissions Nimbus requests.
4. Return to Nimbus and confirm the status shows Connected.
5. Select Sync now to catch up on changes made while the integration was disconnected.

Nimbus recommends connecting integrations with a shared service account rather than a personal account, so that the connection does not break when one person leaves.

## Slack integration

The Nimbus Slack integration posts file activity to Slack channels and lets users share Nimbus files in Slack with previews. If Nimbus notifications stop appearing in Slack, check that the integration is Connected, that the Nimbus app is still installed in the Slack workspace, and that the Nimbus app has been added to the channel. Private Slack channels need the Nimbus app to be invited to the channel before notifications can be posted.

## Google Drive integration

The Nimbus Google Drive integration lets users import files from Google Drive and link Drive folders into Nimbus. If files are missing after an import, check that the connecting account has access to those files in Google Drive; Nimbus can only import files that the connecting account can open. Google Docs, Sheets and Slides are converted to Word, Excel and PowerPoint formats on import.

## Microsoft 365 integration

The Nimbus Microsoft 365 integration lets users open and co-edit Word, Excel and PowerPoint files stored in Nimbus. If files open as read-only, check that the user has edit permission on the file in Nimbus, and that the Microsoft 365 tenant admin has approved the Nimbus app for the organisation. Some Microsoft 365 tenants require admin consent before any user can connect.

## Webhooks

Nimbus webhooks send an HTTP POST request to your endpoint when events such as file uploads, edits, shares or deletions happen. If webhooks stop arriving:

1. Check that your endpoint is reachable over HTTPS and returns a 2xx status code within 10 seconds.
2. Open the webhook in the admin console under Integrations, then Webhooks, and review the delivery log for error codes.
3. Nimbus retries failed deliveries 5 times over 24 hours. After repeated failures the webhook is paused; select Resume once your endpoint is fixed.
4. Verify the signature header on each request with your webhook signing secret to confirm the request came from Nimbus.

## API rate limits on the Pro plan {tier=pro}

The Nimbus API rate limit on the Pro plan is 100 API requests per minute per workspace. Requests over the Pro plan limit receive an HTTP 429 Too Many Requests response with a Retry-After header showing how many seconds to wait. To stay within the Pro plan rate limit, batch requests where possible, cache results, use webhooks instead of polling, and retry with exponential backoff after a 429 response. Workspaces that regularly need more than 100 requests per minute should consider the Enterprise plan.

## API rate limits on the Enterprise plan {tier=enterprise}

The Nimbus API rate limit on the Enterprise plan is 1,000 API requests per minute per workspace. Requests over the Enterprise plan limit receive an HTTP 429 Too Many Requests response with a Retry-After header. Enterprise customers who expect sustained traffic above 1,000 requests per minute, for example during a large migration, should contact their customer success manager in advance to discuss options.

## API authentication errors

An HTTP 401 Unauthorized response means the API key is missing, mistyped or revoked. Create a new API key in the admin console under Integrations, then API keys, and update your application. An HTTP 403 Forbidden response means the API key is valid but does not have permission for that action; check the key's scopes.
