# Setup & Verification Guide

Two halves: **(A)** how to capture the evidence in `screenshots/`, and **(B)** how
to import, configure and verify the workflow yourself.

---

## A. Capturing the evidence

| # | File | What to capture | Where |
| --- | --- | --- | --- |
| 01 | `01-Canvas.png` | Full canvas, zoomed to fit one screen (both intake paths visible) | n8n workflow page |
| 02 | `02-executions.png` | Execution list: green runs + 409 conflicts | n8n → Executions |
| 03 | `03-ocr-run.png` | One execution: OCR text and classification output | Execution detail |
| 03b | `03-ocr-run2.png` | The same run, scrolled to the storage nodes | Execution detail |
| 04 | `04-googlesheet-Inbox.png` | The newest row in the sheet | Google Sheets |
| 05 | `05-Drive-folder.png` | The archived attachment | Google Drive → InboxArchive |
| 06 | `06-slack-approval.png` | The approval message | Slack #inbox-approvals |
| 07 | `07-digest-email.png` | The morning digest | mailbox inbox |
| 08 | `08-approval-queue.png` | Pending vs processed rows in the queue | server terminal |

**Capture rules**

- Browser full screen, bookmarks bar hidden, clean Chrome profile (no work tabs).
- Terminal: dark theme, font 16–18, window 110–130 characters wide.
- Export at 1200–1400 px width; keep files under ~500 KB for Upwork.
- Save with the exact names above so README links resolve.

### Capturing 08 — the approval queue

```bash
docker exec n8n-postgres psql -U n8n_admin -d n8n_prod \
  -P border=2 -P pager=off \
  -c "SELECT q.id AS queue_id, q.message_type, q.status, q.processed,
             left(i.summary, 48) AS summary
      FROM approval_queue q
      JOIN inbox_messages i ON i.id = q.message_id
      ORDER BY q.id;"
```

A good screenshot shows both states: at least one row approved with
`processed = true`, and at least one still `pending` / `processed = false`.

---

## B. Import and configure

1. n8n → **Workflows → Import from file** → `workflow/inbox-agent.json`.
2. Credentials are intentionally absent. Create these:

   | Node(s) | Credential type | Notes |
   | --- | --- | --- |
   | Fetch Demo Emails | Gmail OAuth2 API | needs read access, not just send |
   | Upload to Google Drive | Google Drive OAuth2 API | pick the archive folder |
   | Append to Google Sheets | Google Sheets OAuth2 API | pick spreadsheet + sheet |
   | Send Morning Summary | Gmail OAuth2 API | set the recipient |
   | Notify Approver / Alert on Urgent | Slack API | pick the two channels |
   | Call Vision OCR | Query Auth | parameter name must be `key` |
   | Postgres nodes (8) | PostgreSQL | — |

3. Set the Drive folder, spreadsheet, sheet name, both Slack channels and the
   digest recipient.
4. Publish. Webhook: `POST /webhook/inbox-agent`. The Gmail poll starts immediately.

### The Gmail intake

| Setting | Value in this demo | Why |
| --- | --- | --- |
| Trigger | Schedule, every minute | Polling triggers reset their cursor on every publish and silently skip mail that arrived just before; a schedule is deterministic and can be run manually |
| Query | `DEMO` | Matches the subject/body convention used for the walkthrough |
| Lookback | `receivedAfter = now − 2 minutes` | Keeps each email inside the window long enough to be picked up once, then out of it |
| Read status | `both` | Read or unread, the dedupe key protects against reprocessing |
| Spam | `includeSpamTrash: true` | Test mail from a personal address often lands in Spam — **demo only, turn this off in production** |
| Limit | 1 | One email per poll keeps item pairing simple downstream |

To adapt it to a real inbox, change the query to something like
`subject:invoice has:attachment`, widen the lookback, and set `includeSpamTrash`
to false.

### Node map

| Stage | Nodes |
| --- | --- |
| Gmail intake | Check Inbox (Every minute) → Fetch Demo Emails → Shape Gmail Email |
| Webhook intake | Inbox Webhook → Normalize Email |
| Attachment | Attachment to Binary → Upload to Google Drive → Extract PDF Text → Merge Drive and Text |
| OCR fallback | Text Extracted? → Build Vision Request → Call Vision OCR → Parse Vision Text |
| Classification | Build Classify Request → Classify and Extract (DeepSeek) → Parse Classification → Parsed OK? |
| Dedupe | Check Duplicate → Is Duplicate? |
| Storage | Insert Inbox Message → Append to Google Sheets |
| Approval | Needs Approval? → Ensure Approval Queue Table → Add to Approval Queue → Notify Approver |
| Urgent | Is Urgent? → Alert on Urgent |
| Digest | Morning Digest (08:00) → Digest Query → Build Digest Email → Send Morning Summary |
| Approval poller | Approval Poller (10 min) → Fetch Approved Items → Execute Approved Action → Mark Processed |

---

## C. Verification — one run, three checks

### 1. n8n

Run the workflow once. The latest execution in **Executions** must be green with
no failed nodes.

### 2. Server-side check

```sql
-- (a) the newest inbound record
SELECT id, message_type, status, dedupe_key, sender, summary
FROM inbox_messages ORDER BY id DESC LIMIT 1;

-- (b) its approval-queue row
SELECT id, message_id, status, processed
FROM approval_queue ORDER BY id DESC LIMIT 1;

-- (c) dedupe: sending the same email again must not create a second row
SELECT dedupe_key FROM inbox_messages
WHERE dedupe_key = '<dedupe_key from (a)>'
  AND id <> <id from (a)>;
-- expect: 0 rows
```

### 3. Three-way match

The newest **Google Sheet** row, the archived **Drive** file and the **Slack**
message must describe the same record (sender, subject, timestamp).

---

## D. Before you publish

- [ ] `scripts/sanitize_workflow.py` run on a fresh export (`--aggressive`)
- [ ] `grep -riE "token|secret|password|api_key|xoxb|AIza" .` returns nothing harmful
- [ ] `.env`, `docker-compose.yml`, `*.sql` dumps and SSH keys are **not** in the repo
- [ ] Every `screenshots/*.png` path referenced in README exists
- [ ] `docs/one-page-flow.png` present
- [ ] No placeholder text left (`[your-loom-link]`, `<REDACTED>` in docs)
