# TJ Scheduling

Requests, reschedules and paperwork for Trader Joe's delivery appointments.

## What it does

1. **Picks up orders.** Every 10 minutes it reads the TRADER JOES Smartsheet. Rows with STATUS = APT. REQ. appear under *Ready to request*.
2. **Requests appointments.** One click sends the request in the usual table format to the right DC inbox, chosen from the DC # column (BC Destination No.). See `app/dc_lookup.py`.
3. **Reads DC replies.** It matches each reply by email thread or PO number and reads the date, time and confirmation #. It then writes APT DATE, APT TIME, CONF# and STATUS = BOOKED back to Smartsheet. If a reply can't be read, it lands in *Needs you* so you can enter the appointment by hand.
4. **Reschedules.** 48 hours before an appointment that isn't marked **Keep**, it replies on the thread asking for the next allowed delivery day at least 2 days later. After 3 reschedules on one PO it alerts you instead. All of these numbers can be changed in Settings.
5. **Sends documents.** You upload the combined BOL and Bioterrorism PDF on the Documents page, and the site sends it as a reply-all on the PO's appointment thread. It also has:
   - A **Sent outside site** button with undo.
   - Bulk upload that matches files by the PO number in the file name.
   - Auto-detection of PDFs you send from the mailbox on a PO thread.
   - A daily reminder email for shipped POs that are still missing their document.

## Setup

### 1. Entra ID app registration (IT admin)

- **Redirect URI** (Web): `https://<your-render-url>/auth/callback`
- **Delegated permissions:** `openid`, `profile`, `email` (for sign-in)
- **Application permissions:** `Mail.ReadWrite`, `Mail.Send`. Grant admin consent.
- **Limit to the scheduling mailbox** with Exchange Online RBAC for Applications.
- **Create a client secret.**

### 2. Smartsheet

Go to Apps & Integrations, then API Access, and generate a token.

### 3. Render

1. Push this repo to GitHub.
2. In Render, choose New, then Blueprint, and pick the repo. `render.yaml` creates the web service and a 1 GB disk for the database and PDFs.
3. Fill in the environment variables marked `sync: false`.
4. Keep `--workers 1` in the start command so the background checks run only once.

## Run locally with demo data

```
pip install -r requirements.txt
DEMO_MODE=1 DEMO_NOW=2026-10-05T10:00 python -m app.demo
DEMO_MODE=1 DEMO_NOW=2026-10-05T10:00 python wsgi.py
```

Demo mode skips sign-in and sends nothing.

## Still open

- **Requested date and time rule.** For now it defaults to the first allowed day at least 3 days out at 08:00, and each request waits for you to click Send.
- **DRY/COOLER value.** Temp control DCs are sent as COOLER, and mixing centers as DRY. This needs confirming.
- **DC reply parsing.** It's tuned without real DC replies yet. Send a few samples to tighten it up.
