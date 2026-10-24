"""Reach a human only when needed. SMS via Twilio if configured, otherwise a console stub.
Set TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, NOTIFY_TO to enable real texts."""
import os, requests


def send(msg):
    sid, tok, frm, to = (os.environ.get(k) for k in ("TWILIO_SID", "TWILIO_TOKEN", "TWILIO_FROM", "NOTIFY_TO"))
    if not all((sid, tok, frm, to)):
        print(f"[notify:stub] {msg}")
        return False
    r = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                      auth=(sid, tok), data={"From": frm, "To": to, "Body": msg[:300]}, timeout=15)
    return r.ok
