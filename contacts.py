"""Who to ask about a gap: contacts read from the registry record itself. No guessing, no scraping.

Ranked by how directly each one answers questions about posted results:
  1. resultsSection.moreInfoModule.pointOfContact  - the registry's named contact for results questions
  2. contactsLocationsModule.centralContacts        - usually removed once a trial completes
  3. sponsorCollaboratorsModule.responsibleParty    - the investigator legally responsible for the record
  4. contactsLocationsModule.overallOfficials       - PI / study director (the registry has no emails for these)
  5. sponsorCollaboratorsModule.leadSponsor         - organization only, last resort
Only the first two can carry an email. A contact without one is still worth showing to the human.
"""
import re

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _c(role, name, org, email, phone, path):
    email = (email or "").strip()
    return {"role": role, "name": (name or "").strip(), "organization": (org or "").strip(),
            "email": email if EMAIL.match(email) else "", "phone": (phone or "").strip(), "source_path": path}


def extract(study):
    p = study.get("protocolSection", {}) or {}
    cl = p.get("contactsLocationsModule", {}) or {}
    sp = p.get("sponsorCollaboratorsModule", {}) or {}
    sponsor = (sp.get("leadSponsor") or {}).get("name", "")
    out = []
    poc = ((study.get("resultsSection", {}) or {}).get("moreInfoModule", {}) or {}).get("pointOfContact")
    if poc:
        out.append(_c("Results point of contact", poc.get("title"), poc.get("organization"), poc.get("email"),
                      " ext. ".join(filter(None, [poc.get("phone"), poc.get("phoneExt")])),
                      "resultsSection.moreInfoModule.pointOfContact"))
    for i, c in enumerate(cl.get("centralContacts", []) or []):
        out.append(_c("Central contact", c.get("name"), sponsor, c.get("email"), c.get("phone"),
                      f"protocolSection.contactsLocationsModule.centralContacts[{i}]"))
    rp = sp.get("responsibleParty") or {}
    if rp.get("investigatorFullName"):
        out.append(_c("Responsible party", rp.get("investigatorFullName"), rp.get("investigatorAffiliation"), "", "",
                      "protocolSection.sponsorCollaboratorsModule.responsibleParty"))
    for i, o in enumerate(cl.get("overallOfficials", []) or []):
        role = (o.get("role") or "official").replace("_", " ").title()
        out.append(_c(role, o.get("name"), o.get("affiliation"), "", "",
                      f"protocolSection.contactsLocationsModule.overallOfficials[{i}]"))
    if sponsor:
        out.append(_c("Lead sponsor", "", sponsor, "", "", "protocolSection.sponsorCollaboratorsModule.leadSponsor"))
    return out


def recipient(contacts):
    """The best contact to address: the highest-ranked one with an email, else the highest-ranked one."""
    contacts = contacts or []
    return next((c for c in contacts if c["email"]), contacts[0] if contacts else None)
