"""Reach a human only when needed. Push to a phone via ntfy and/or SMS via Twilio, otherwise a console stub.
ntfy:   set NTFY_TOPIC (install the ntfy app and subscribe to the same topic). Optional NTFY_SERVER.
Twilio: set TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, NOTIFY_TO."""
import os, requests


def channels():
    out = []
    if os.environ.get("NTFY_TOPIC"):
        out.append("ntfy")
    if all(os.environ.get(k) for k in ("TWILIO_SID", "TWILIO_TOKEN", "TWILIO_FROM", "NOTIFY_TO")):
        out.append("twilio")
    return out


def _ntfy(msg):
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    halted = "HALTED" in msg
    r = requests.post(f"{server}/{os.environ['NTFY_TOPIC']}", data=msg.encode(), timeout=15,
                      headers={"Title": "HerEvidence stopped itself" if halted else "HerEvidence",
                               "Priority": "high" if halted else "default",
                               "Tags": "warning" if halted else "white_check_mark"})
    return r


def _twilio(msg):
    sid, tok, frm, to = (os.environ[k] for k in ("TWILIO_SID", "TWILIO_TOKEN", "TWILIO_FROM", "NOTIFY_TO"))
    return requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                         auth=(sid, tok), data={"From": frm, "To": to, "Body": msg[:300]}, timeout=15)


def send(msg):
    chans = channels()
    if not chans:
        print(f"[notify:stub] {msg}")
        return False
    ok = False
    for name in chans:
        try:
            r = (_ntfy if name == "ntfy" else _twilio)(msg)
            if r.ok:
                ok = True
            else:   # say so loudly: a silent failure on stage looks like a broken agent
                print(f"[notify:{name}] FAILED {r.status_code}: {r.text[:200]}")
        except requests.RequestException as e:
            print(f"[notify:{name}] FAILED: {e}")
    return ok


if __name__ == "__main__":
    print("channels:", channels() or "none (set NTFY_TOPIC)")
    print("sent" if send("HerEvidence test: notifications are working.") else "not sent")
