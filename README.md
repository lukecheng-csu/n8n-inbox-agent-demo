# n8n Inbox Agent — Email → OCR → Classification → Sheet/Drive → Slack Approval → Daily Digest

An end-to-end, production-tested n8n automation that turns a shared inbox into a
structured, human-approved workflow. Every inbound email is parsed, attachments are
OCR'd when needed, the content is classified, the record is written to Google Sheets,
originals are archived to Google Drive, the team gets a Slack approval message, and a
daily digest is emailed out.

> This repository is a **sanitized demo of a real client build**. Credentials, tokens and
> customer data have been removed — see [Security](#security--sanitization).

---

## 1. What problem it solves

A shared inbox is a black hole: emails pile up, attachments get lost, nothing is tracked,
and nobody knows who approved what.

This agent makes the inbox auditable:

| Client pain | What the agent does |
| --- | --- |
| "We lose track of what came in." | Every email becomes a row in Google Sheets. |
| "Attachments are scattered." | Files are archived to a structured Drive folder. |
| "Someone has to read every email." | Text + OCR classification runs automatically. |
| "Multiple people forward the same email." | Server-side de-duplication + explicit 409 handling. |
| "Nothing gets approved formally." | A pending row is queued and a Slack approval message is sent. |
| "I forget what happened yesterday." | A scheduled morning digest email is sent. |

### Requirements → Evidence

Each claim below is backed by a file in this repo.

| Requirement | Evidence |
| --- | --- |
| Real, working workflow (not a mockup) | [`workflow/inbox-agent.json`](workflow/inbox-agent.json) + `screenshots/01-canvas.png` |
| Runs in production, repeatedly | `screenshots/02-executions.png` (execution list w/ success + 409 conflicts) |
| OCR + classification actually execute | `screenshots/03-ocr-run.png` (per-node data flow of one run) |
| Data lands in the sheet | `screenshots/04-sheet-row.png` |
| Attachments archived | `screenshots/05-drive-folder.png` |
| Approval notification sent | `screenshots/06-slack-approval.png` |
| Scheduled digest works | `screenshots/07-digest-email.png` |
| Queue / dedupe / processed flag correct | `docs/setup-guide.md` §Verification |

---

## 2. Architecture

```
IMAP / Gmail trigger
        │
        ▼
  Fetch attachments ──► (needs OCR?) ──► OCR service ──► extracted text
        │                                    │
        └──────────────► Classify (text) ◄───┘
                              │
              ┌───────────────┼────────────────┬──────────────────┐
              ▼               ▼                ▼                  ▼
      Google Sheets     Google Drive     Approval queue      Slack channel
      (append row)      (archive file)   (pending row)       (#inbox-approvals)
                              │
                              ▼
                    Daily digest (scheduled, 163 email)
```

**Stack:** n8n · PostgreSQL (queue + de-dupe) · IMAP · Google Sheets API ·
Google Drive API · Slack API · OCR (text extraction for images/PDFs) · SMTP (digest).

---

## 3. Repository layout

```
n8n-inbox-agent-demo/
├── README.md
├── workflow/
│   └── inbox-agent.json          # sanitized workflow export
├── screenshots/                  # 7 screenshots, see §Evidence
├── docs/
│   ├── setup-guide.md            # how to import, configure, verify
│   └── one-page-flow.png         # single-page flow diagram
└── scripts/
    └── sanitize_workflow.py      # removes credentials/pinData before publishing
```

---

## 4. Quick start (adapt it to your own stack)

1. Import `workflow/inbox-agent.json` into your n8n instance.
2. Recreate credentials (they are intentionally absent): IMAP, Google Sheets,
   Google Drive, Slack, SMTP, PostgreSQL.
3. Point the IMAP node at your shared inbox and set the Drive folder ID.
4. Run the verification checklist in [`docs/setup-guide.md`](docs/setup-guide.md).

---

## 5. Security & sanitization

The exported workflow was cleaned with `scripts/sanitize_workflow.py`:

```bash
python3 scripts/sanitize_workflow.py inbox-agent.json clean.json --aggressive
```

It removes node/root `credentials`, `pinData`, `webhookId`, and masks tokens,
emails and long IDs. **Never commit `.env`, `docker-compose.yml`, or DB dumps.**

---

## 6. Verification (how the demo is proven)

One full run must satisfy all three:

1. **n8n** — latest execution is green, no failed nodes.
2. **Server check script** — `inbox_messages` has a new row, `approval_queue` has a
   matching `pending` row, and the duplicate check returns 0 rows.
3. **Three-way match** — the newest Sheet row, the archived Drive file, and the Slack
   message describe the same record.

> Three-way match = the whole chain (email → storage → approval) is verified.

---

## 7. Contact

Available for similar n8n / workflow-automation builds.
Loom walkthrough: `[your-loom-link]`
