"""Microsoft Graph mail client (app-only, client credentials).

Needs application permissions Mail.ReadWrite + Mail.Send, scoped to the
scheduling mailbox with Exchange RBAC for Applications.
"""
import base64
import time

import requests

GRAPH = "https://graph.microsoft.com/v1.0"
SMALL_ATTACHMENT_LIMIT = 3 * 1024 * 1024
CHUNK = 4 * 320 * 1024  # upload-session chunks must be multiples of 320 KiB


class GraphError(Exception):
    pass


class GraphClient:
    def __init__(self, tenant_id, client_id, client_secret, mailbox):
        self.tenant_id, self.client_id, self.client_secret = tenant_id, client_id, client_secret
        self.mailbox = mailbox
        self._token, self._expires = None, 0

    # -- plumbing ---------------------------------------------------------
    def _get_token(self):
        if self._token and time.time() < self._expires - 120:
            return self._token
        r = requests.post(
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token",
            data={"client_id": self.client_id, "client_secret": self.client_secret,
                  "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"},
            timeout=30)
        if r.status_code != 200:
            raise GraphError(f"Token request failed: {r.status_code} {r.text[:300]}")
        data = r.json()
        self._token, self._expires = data["access_token"], time.time() + int(data["expires_in"])
        return self._token

    def _req(self, method, path, **kw):
        url = path if path.startswith("http") else f"{GRAPH}/users/{self.mailbox}{path}"
        headers = kw.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._get_token()}"
        for attempt in range(4):
            r = requests.request(method, url, headers=headers, timeout=60, **kw)
            if r.status_code in (429, 503, 504):
                time.sleep(int(r.headers.get("Retry-After", 2 ** attempt)))
                continue
            break
        if r.status_code >= 400:
            raise GraphError(f"{method} {path} failed: {r.status_code} {r.text[:300]}")
        return r.json() if r.content else {}

    # -- sending ----------------------------------------------------------
    def send_new(self, to, subject, html):
        """Create + send a new message. Returns (message_id, conversation_id)."""
        draft = self._req("POST", "/messages", json={
            "subject": subject,
            "body": {"contentType": "HTML", "content": html},
            "toRecipients": [{"emailAddress": {"address": to}}],
        })
        self._req("POST", f"/messages/{draft['id']}/send")
        return draft["id"], draft["conversationId"]

    def reply_all(self, message_id, html, attachment=None):
        """Reply-all on a thread. attachment = (filename, bytes) or None."""
        draft = self._req("POST", f"/messages/{message_id}/createReplyAll", json={})
        # Put our text above the quoted thread.
        existing = draft.get("body", {}).get("content", "")
        self._req("PATCH", f"/messages/{draft['id']}",
                  json={"body": {"contentType": "HTML", "content": html + existing}})
        if attachment:
            self._attach(draft["id"], *attachment)
        self._req("POST", f"/messages/{draft['id']}/send")
        return draft["id"]

    def _attach(self, draft_id, filename, data):
        if len(data) < SMALL_ATTACHMENT_LIMIT:
            self._req("POST", f"/messages/{draft_id}/attachments", json={
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": filename, "contentType": "application/pdf",
                "contentBytes": base64.b64encode(data).decode()})
            return
        session = self._req("POST", f"/messages/{draft_id}/attachments/createUploadSession", json={
            "AttachmentItem": {"attachmentType": "file", "name": filename, "size": len(data),
                               "contentType": "application/pdf"}})
        upload_url, total = session["uploadUrl"], len(data)
        for start in range(0, total, CHUNK):
            chunk = data[start:start + CHUNK]
            end = start + len(chunk) - 1
            r = requests.put(upload_url, data=chunk, timeout=120, headers={
                "Content-Length": str(len(chunk)), "Content-Range": f"bytes {start}-{end}/{total}"})
            if r.status_code >= 400:
                raise GraphError(f"Attachment upload failed: {r.status_code} {r.text[:300]}")

    # -- reading ----------------------------------------------------------
    def unread_inbox(self, top=50):
        data = self._req("GET", "/mailFolders/inbox/messages", params={
            "$filter": "isRead eq false", "$top": str(top),
            "$select": "id,subject,uniqueBody,from,conversationId,receivedDateTime"})
        return data.get("value", [])

    def sent_since(self, iso_utc, top=50):
        data = self._req("GET", "/mailFolders/sentitems/messages", params={
            "$filter": f"sentDateTime ge {iso_utc}", "$top": str(top),
            "$select": "id,subject,conversationId,hasAttachments,sentDateTime"})
        return data.get("value", [])

    def attachment_names(self, message_id):
        data = self._req("GET", f"/messages/{message_id}/attachments", params={"$select": "name"})
        return [a.get("name", "") for a in data.get("value", [])]

    def mark_read(self, message_id):
        self._req("PATCH", f"/messages/{message_id}", json={"isRead": True})

    def latest_in_conversation(self, conversation_id):
        data = self._req("GET", "/messages", params={
            "$filter": f"conversationId eq '{conversation_id}'",
            "$select": "id,receivedDateTime", "$top": "50"})
        msgs = sorted(data.get("value", []), key=lambda m: m.get("receivedDateTime", ""), reverse=True)
        return msgs[0]["id"] if msgs else None

    def search_po(self, po_display):
        """Find messages mentioning a PO number. Returns list of {id, conversationId}."""
        data = self._req("GET", "/messages", params={
            "$search": f'"{po_display}"', "$select": "id,conversationId,subject,receivedDateTime",
            "$top": "25"})
        return data.get("value", [])


class DemoGraph:
    """Stand-in used in demo mode: records what would have been sent."""

    def __init__(self):
        self.outbox = []

    def send_new(self, to, subject, html):
        self.outbox.append(("new", to, subject))
        n = len(self.outbox)
        return f"demo-msg-{n}", f"demo-conv-{n}"

    def reply_all(self, message_id, html, attachment=None):
        self.outbox.append(("reply", message_id, attachment[0] if attachment else None))
        return f"demo-reply-{len(self.outbox)}"

    def unread_inbox(self, top=50):
        return []

    def sent_since(self, iso_utc, top=50):
        return []

    def attachment_names(self, message_id):
        return []

    def mark_read(self, message_id):
        pass

    def latest_in_conversation(self, conversation_id):
        return f"{conversation_id}-latest"

    def search_po(self, po_display):
        return []
