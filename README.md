# n8n Inbox Agent — Email → OCR → Classification → Sheet + Drive → Slack Approval → Daily Digest

An end-to-end n8n automation that turns a shared inbox into structured, auditable
records. Every inbound email is read, attachments are OCR'd when needed, the email
is classified, the record is written to Google Sheets, originals are archived to
Google Drive, the team gets a Slack message, and a daily digest is emailed out.

> This repository is a **sanitized demo built for a real Upwork job posting**.
> Credentials, tokens and account-specific IDs have been removed — see
> [Security](#security--sanitization).

---

## The brief this was built against

> Our operations team spends hours each week reading emails and PDF attachments
> (invoices, purchase orders, remittances) and typing the details into spreadsheets.
>
> We want an AI-assisted workflow that:
>
> - Monitors a shared inbox (Gmail or IMAP) and reads PDF attachments, including scanned ones
> - Classifies each email as urgent, request, invoice, or routine
> - Extracts key fields (sender, PO or invoice number, amount, due date) into Google Sheets or Airtable
> - Saves each attachment to an organized Google Drive folder, linked to its record
> - Sends a Slack alert for urgent items and a short morning summary email
> - Puts anything involving money or an outgoing message into an "approval queue", so nothing is sent without a human OK
>
> Requirements: experience with n8n or Make, an LLM API (Claude or OpenAI), and OCR or PDF
> extraction. Each workflow needs validation, retries, failure alerts, and duplicate checks.
> Everything is built in our accounts and documented so someone else can maintain it.

*Source: a public Upwork job posting (October 2026). This repository is an independent
demo built in response — not a paid client engagement.*

---

## 1. What problem it solves

A shared inbox is a black hole: emails pile up, attachments get lost, nothing is
tracked, and nobody knows who approved what.

This agent makes the inbox auditable:

| Pain | What the agent does |
| --- | --- |
| "We lose track of what came in." | Every email becomes a row in Google Sheets. |
| "Attachments are scattered." | Files are archived to a dedicated Drive folder, linked to the row. |
| "Someone has to read every email." | Text extraction + Google Vision OCR, then LLM classification. |
| "People forward the same thing twice." | Server-side de-duplication, with an explicit 409 response. |
| "Nothing gets approved formally." | Anything involving money or a reply waits in an approval queue. |
| "I forget what happened yesterday." | A scheduled morning digest email. |

## 2. How it works

```
Two intake paths:

  Webhook (POST /webhook/inbox-agent)        ← for integrations and testing
  Gmail (poll every minute, 2-minute window) ← for a real inbox

        │
        ▼
Has attachment? ── yes ──► Google Drive upload ──► PDF text extraction
        │                        │                        │
        │                        │                 empty text? ── yes ──► Google Vision OCR
        │                        │                        │                        │
        ▼                        ▼                        ▼                        ▼
  email body text  ────────────────────────────►  LLM classify + extract (DeepSeek)
                                                          │
                                                   validation ── fail ──► needs review
                                                          │
                                                    duplicate? ── yes ──► 409, no new row
                                                          │
                                   ┌──────────────────────┼───────────────────────┐
                                   ▼                      ▼                       ▼
                            Google Sheets           Google Drive           approval queue
                            (append row)          (link on the row)      (pending, Postgres)
                                                                                  │
                                                              ┌───────────────────┘
                                                              ▼
                                                   Slack #inbox-approvals
                                                   (urgent items → #inbox-urgent)

Daily 08:00 → digest query → Gmail  (counts by type and status, last 24h)
Every 10 min → approval poller → executes only rows a human marked approved
```

**Stack:** n8n · PostgreSQL (storage, queue, de-duplication) · Gmail API ·
Google Sheets API · Google Drive API · Google Vision OCR ·
DeepSeek (swappable for OpenAI/Claude) · Slack API.

![One-page flow](docs/one-page-flow.png)

## 3. Requirements → evidence

| What the brief asks for | How it is met | Evidence |
| --- | --- | --- |
| Monitors a shared inbox (Gmail or IMAP), reads PDFs including scanned ones | Two intake paths: a webhook for integrations, and a Gmail poll (every minute, 2-minute lookback). Scanned PDFs fall back to Google Vision OCR. | `screenshots/01-Canvas.png`, `screenshots/03-ocr-run.png` |
| Classifies each email as urgent, request, invoice, or routine | One LLM call with a strict JSON schema and a fixed vocabulary. | `screenshots/03-ocr-run.png` |
| Extracts sender, PO or invoice number, amount, due date into Sheets or Airtable | All four fields plus vendor and currency, appended as one sheet row per email. | `screenshots/04-googlesheet-Inbox.png` |
| Saves each attachment to a Drive folder, linked to its record | Drive upload runs before text extraction; the sheet row stores the link. | `screenshots/05-Drive-folder.png` |
| Slack alert for urgent items, short morning summary email | Dedicated `#inbox-urgent` branch, plus a daily 08:00 digest through Gmail. | `screenshots/06-slack-approval.png`, `screenshots/07-digest-email.png` |
| Approval queue — nothing sent without a human OK | Rows sit in `approval_queue` as `pending`; the poller only acts on rows a person set to `approved`. | `screenshots/08-approval-queue.png` |
| Validation, retries, failure alerts, duplicate checks | Field validation routes bad extractions to review; API calls retry; a separate Error Trigger workflow raises failures; a unique dedupe key returns 409. | `screenshots/02-executions.png` |
| Documented so someone else can maintain it | Setup guide with credential table, node map and verification queries. | `docs/setup-guide.md` |

## 4. Repository layout

```
n8n-inbox-agent-demo/
├── README.md
├── workflow/
│   └── inbox-agent.json      # sanitized export
├── screenshots/              # canvas, executions, OCR run, sheet, Drive, Slack, digest, queue
├── docs/
│   ├── setup-guide.md        # import, configure, verify
│   └── one-page-flow.png     # one-screen overview
└── scripts/
    └── sanitize_workflow.py  # strips credentials/pinData before publishing
```

## 5. Importing it

1. Import `workflow/inbox-agent.json` into n8n.
2. Recreate credentials — they are intentionally absent:

   | Node | Credential type |
   | --- | --- |
   | Fetch Demo Emails | Gmail OAuth2 API |
   | Google Drive upload | Google Drive OAuth2 API |
   | Google Sheets append | Google Sheets OAuth2 API |
   | Morning digest | Gmail OAuth2 API |
   | Slack alerts (×2) | Slack API |
   | Vision OCR | Query Auth (parameter name `key`) |
   | Database nodes | PostgreSQL |

3. Select the Drive folder, spreadsheet, Slack channels and digest recipient.
4. Adjust the Gmail search query (`DEMO` in this demo) to match your own inbox
   convention — see §8.
5. Publish. The webhook is then available at `/webhook/inbox-agent`, and the
   Gmail poll starts running every minute.

## 6. Verification

One full run must satisfy all three:

1. **n8n** — the latest execution is green, no failed nodes.
2. **Server check** — the newest `inbox_messages` row, a matching `pending` row in
   `approval_queue`, and a duplicate check that returns 0 rows.
3. **Three-way match** — the newest Sheet row, the Drive file and the Slack message
   describe the same record.

```sql
-- newest record
SELECT id, message_type, status, dedupe_key, summary
FROM inbox_messages ORDER BY id DESC LIMIT 1;

-- its approval row
SELECT id, approval_queue.status, processed
FROM approval_queue ORDER BY id DESC LIMIT 1;

-- dedupe: re-sending the same email must not create a second row
SELECT dedupe_key FROM inbox_messages
WHERE dedupe_key = '<key from the first query>'
  AND id <> <id from the first query>;
-- expect: 0 rows
```

## 7. Security & sanitization

The export was cleaned with `scripts/sanitize_workflow.py`:

```bash
python3 scripts/sanitize_workflow.py inbox-agent.json clean.json --aggressive
```

It removes node/root `credentials`, `pinData` and `webhookId`, and masks tokens,
emails and long account IDs. Never commit `.env`, `docker-compose.yml` or DB dumps.

## 8. Known limitations

- **Polling triggers lose mail across a restart.** n8n resets a polling trigger's
  cursor every time the workflow is published, so anything that arrived just before
  a publish is skipped. This build avoids the problem by polling on a schedule and
  querying Gmail directly (`receivedAfter` window) instead of relying on a cursor.
  In production, the safer pattern is an unread filter plus marking each message as
  handled once its record exists.
- **Self-sent test mail lands in Spam.** Gmail classified the 163.com → Gmail test
  email as spam ("similar to messages that were identified as spam in the past").
  The demo query sets `includeSpamTrash: true` so the walkthrough still completes;
  in production that flag should be off, with spam handled separately.
- **Gmail's `from` field is structured, not a string.** It arrives as an object
  (`{text, value:[{address, name}]}`). Casting it directly yields `[object Object]`;
  the `Shape Gmail Email` node unwraps it layer by layer.
- Google Vision's synchronous `files:annotate` handles the first 5 pages of a PDF.
  Longer scanned documents need the asynchronous batch API with Cloud Storage.
- OCR failures are non-fatal: the email continues to review rather than being dropped.
- The LLM step uses DeepSeek here; switching to OpenAI or Claude is a change of
  URL, model name and credential in one node.

## 9. Contact

Available for similar n8n / workflow-automation builds.
