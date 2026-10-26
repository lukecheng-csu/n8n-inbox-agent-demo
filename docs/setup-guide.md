# Setup & Verification Guide

This guide has two halves: (A) how to **capture the evidence** and (B) how to
**import + verify** the workflow after cloning.

---

## A. How to capture the screenshots

All captures happen on your own machine — no second party needed. Priority order:

| # | What to capture | Where | Proves |
| --- | --- | --- | --- |
| 01 | Full canvas | n8n workflow page, zoomed to fit one screen | The workflow really exists |
| 02 | Execution list | n8n → Executions, filtered to this inbox workflow | It has run many times; success + 409 conflicts |
| 03 | One execution | Execution #220 detail | OCR + classification node-by-node data flow |
| 04 | Sheet row | Google Sheets → Inbox tab | Data lands in the sheet |
| 05 | Drive folder | Google Drive → InboxArchive | Attachments archived |
| 06 | Slack message | Slack #inbox-approvals | Approval notification sent |
| 07 | Digest email | 163 mailbox inbox | Scheduled digest works |
| (08) | DB check | server terminal, run check script | Queue / dedupe / processed flag |

**Capture rules**
- Browser: full screen, bookmarks bar hidden.
- Terminal: dark theme, larger font.
- Window width **1200–1400 px** (fits Upwork's narrow preview without getting blurry).
- Save as `screenshots/0X-name.png` exactly as listed above.

---

## B. Import the workflow

1. n8n → **Workflows → Import from file** → choose `workflow/inbox-agent.json`.
2. Open the imported workflow. Nodes will show missing-credential warnings — expected.
3. Recreate credentials:

   | Node | Credential type |
   | --- | --- |
   | IMAP trigger | IMAP / Gmail |
   | Google Sheets | Google Sheets OAuth2 |
   | Google Drive | Google Drive OAuth2 |
   | Slack | Slack OAuth2 / Bot token |
   | Digest email | SMTP |
   | DB nodes | PostgreSQL |

4. Replace the placeholders left by sanitization (`<REDACTED>`, `<drive-id>`,
   `<email>`) with your own values.
5. Set the Drive archive folder ID and the Slack channel.
6. Save and **test each node once**.

---

## C. Verification — one full run, three checks

### 1. n8n execution
Run the workflow manually once. In **Executions**, the latest run must be **green**
with no failed nodes.

### 2. Server-side check
Run the check script on the server (adapt the queries to your schema):

```sql
-- (a) new inbound row exists
SELECT id, received_at, subject
FROM inbox_messages
ORDER BY received_at DESC
LIMIT 1;

-- (b) a matching pending approval row was queued
SELECT id, message_id, status
FROM approval_queue
WHERE status = 'pending'
ORDER BY id DESC
LIMIT 1;

-- (c) dedupe works: re-inserting the same message must return 0 rows
SELECT id
FROM inbox_messages
WHERE message_id = '<the message id from (a)>'
  AND id <> <the id from (a)>;
-- expect: 0 rows
```

All three conditions must pass.

### 3. Three-way match
Confirm the newest **Google Sheet** row, the archived **Drive** file, and the
**Slack** message all describe the same record (same sender / subject / timestamp).

> Three-way match = "email → storage → approval" chain is fully working.

Record a Loom once, doing exactly this sequence — that is the demo video.

---

## D. Before you publish

- [ ] Run `python3 scripts/sanitize_workflow.py workflow/inbox-agent.json clean.json --aggressive`
      and move `clean.json` into `workflow/`.
- [ ] Grep the repo for leaks: `grep -riE "token|secret|password|api_key" .`
- [ ] Confirm `.env`, `docker-compose.yml`, `*.sql`, `*.bak` are **not** present.
- [ ] Replace `[your-loom-link]` in `README.md`.
- [ ] Add `docs/one-page-flow.png`.
- [ ] All 7 screenshots present in `screenshots/`.
