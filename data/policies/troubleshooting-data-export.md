---
title: Troubleshooting Data Export
doc_type: troubleshooting
tier: all
---

## What a Nimbus data export contains

Data export is available on every Nimbus plan. A Nimbus export contains two parts:

- A ZIP archive of the original files, in their original formats and folder structure. The export includes the current version of each file; earlier versions are not included.
- A CSV file of the workspace activity log, listing each event with its date, time, user, action and file path.

Files in the trash are not exported. Comments on files are included in the activity log CSV.

## Starting an export

Workspace owners and admins can start an export from the admin console:

1. Go to the admin console, then Data, then Export.
2. Choose whether to export the whole workspace or selected folders.
3. Choose whether to include the activity log CSV.
4. Select Start export.

Small exports are ready to download from the Export page within a few minutes. Only one export can run at a time for each workspace.

## Large exports delivered by email

Large Nimbus exports are prepared in the background and delivered by email. When a large export is ready, Nimbus emails the person who started it a download link. The download link is valid for 7 days. After 7 days the link expires and the export must be started again. Large exports can take several hours to prepare depending on the number and size of files. If the email does not arrive, check the spam or junk folder and confirm the export shows as Complete on the Export page.

## Free plan export limits {tier=free}

Free plan exports are limited to 2 GB per export request. If a Free plan workspace holds more than 2 GB of data, export it in parts by selecting a few folders at a time, keeping each export request under 2 GB. An export request over 2 GB on the Free plan is stopped with a message asking you to reduce the selection. Free plan workspaces can run as many export requests as needed.

## Pro plan export limits {tier=pro}

Pro plan exports have no per-request size limit. Very large Pro plan exports are split into several ZIP files of up to 50 GB each, all listed in the same download email. Each download link in the email is valid for 7 days.

## Enterprise export options {tier=enterprise}

Enterprise plan exports have no per-request size limit and are split into ZIP files of up to 50 GB each. Enterprise admins can also export the full admin audit log as CSV alongside the activity log. For very large workspaces, the customer success manager can arrange a scheduled bulk export to the customer's own cloud storage bucket.

## Fixing common export problems

If an export fails or the files look wrong, try the following:

1. Export stuck at Preparing for more than 24 hours: cancel it from the Export page and start it again. If it fails a second time, contact support with the export ID shown on the Export page.
2. Download link expired: the link is valid for 7 days only. Start a new export.
3. ZIP file will not open: the download may be incomplete. Check that the downloaded file size matches the size in the email, then download again using a stable connection.
4. File names look garbled: use an archive tool that supports UTF-8 file names.
5. Some files missing: check that the user who started the export has access to every folder. Exports only include files the person starting the export can open.
6. CSV shows odd characters in a spreadsheet: import the CSV as UTF-8 rather than opening it directly.

## Exporting before cancellation

When a Nimbus workspace is cancelled, data is kept for 30 days and then permanently deleted. During those 30 days the workspace owner can still sign in and export data. Nimbus recommends exporting before cancelling, and allowing time for large exports to be prepared and downloaded before the 7-day link expires.
