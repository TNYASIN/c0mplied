"""Who a draft goes to (registry contacts) and the PubMed cross-check of linked publications."""
import json, sqlite3
from pathlib import Path

import contacts, pubmed
from auditor import publication_check
from fetch_trials import normalize_trial


def _raw(nct):
    return json.loads(Path(f"data/real_gold/{nct}.json").read_text(encoding="utf-8"))


def test_results_point_of_contact_is_preferred_recipient():
    raw = _raw("NCT00381303")
    t = normalize_trial(raw)
    to = contacts.recipient(t["contacts"])
    poc = raw["resultsSection"]["moreInfoModule"]["pointOfContact"]
    assert to["role"] == "Results point of contact" and to["email"] == poc.get("email", "")
    assert to["source_path"] == "resultsSection.moreInfoModule.pointOfContact"
    assert any(c["role"] == "Lead sponsor" for c in t["contacts"])


def test_no_email_is_ever_invented():
    study = {"protocolSection": {"contactsLocationsModule": {"overallOfficials": [{"name": "A. PI", "role": "PRINCIPAL_INVESTIGATOR"}],
                                                             "centralContacts": [{"name": "B", "email": "not-an-email"}]}}}
    cs = contacts.extract(study)
    assert all(c["email"] == "" for c in cs)
    assert contacts.recipient(cs)["name"] == "B"          # highest-ranked contact, even without an email
    assert contacts.recipient([]) is None


def test_registry_references_are_kept():
    t = normalize_trial(_raw("NCT00381303"))
    assert {"24396625", "20855799"} <= {r["pmid"] for r in t["references"]}


def test_efetch_xml_parsing():
    xml = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID Version="1">123</PMID><Article>
      <Journal><JournalIssue><PubDate><Year>2020</Year></PubDate></JournalIssue><Title>J Test</Title></Journal>
      <ArticleTitle>A <i>trial</i></ArticleTitle><ELocationID EIdType="doi">10.1/x</ELocationID>
      <Abstract><AbstractText Label="RESULTS">Effect was larger in women than men (P = .01).</AbstractText></Abstract>
      </Article></MedlineCitation><PubmedData><ReferenceList><Reference><ArticleIdList><ArticleId IdType="pubmed">999</ArticleId>
      </ArticleIdList></Reference></ReferenceList></PubmedData></PubmedArticle></PubmedArticleSet>"""
    [p] = pubmed.parse(xml)
    assert (p["pmid"], p["title"], p["journal"], p["year"], p["doi"]) == ("123", "A trial", "J Test", "2020", "10.1/x")
    assert pubmed.find_sex_analysis(p) == "Effect was larger in women than men (P = .01)."


def test_sex_analysis_matcher_skips_covariates_enrollment_and_plans():
    no = ["Analyses were adjusted for age, sex and baseline severity.", "41% were women and 59% were men.",
          "The study was designed to assess sex-based differences in response.",
          "Randomization was stratified by sex and site."]
    yes = ["Gender and minority status moderated outcome (P = .014).", "Response rates in women and men were 50.9% and 58.5%.",
           "Treatment effects differed by sex."]
    for s in no:
        assert pubmed.find_sex_analysis({"abstract": s}) == "", s
    for s in yes:
        assert pubmed.find_sex_analysis({"abstract": s}) == s, s
    # Aims and methods sections never count, even when they name a sex comparison.
    assert pubmed.find_sex_analysis({"abstract": "OBJECTIVE: To compare outcomes by sex."}) == ""


def test_frozen_snapshot_finds_publication_that_fills_a_registry_gap():
    # NCT00043550's registry results have no by-sex outcome, but its linked paper reports gender moderation.
    status, pubs = pubmed.load_gold("NCT00043550")
    assert status == "OK" and pubs
    v = publication_check("NCT00043550", status, pubs)
    assert v["label"] == "MENTIONED_IN_PUBLICATION" and v["pmid"] == "22152401"
    assert v["sentence"] in next(p for p in pubs if p["pmid"] == "22152401")["abstract"]


def test_publication_check_labels():
    assert publication_check("X", None, [])["label"] == "NOT_CHECKED"
    assert publication_check("X", "ERROR", [])["label"] == "NOT_CHECKED"
    assert publication_check("X", "OK", [])["label"] == "NO_LINKED_PUBLICATION"
    assert publication_check("X", "OK", [{"pmid": "1", "title": "t", "abstract": "Pooled results."}])["label"] == "NOT_FOUND_IN_ABSTRACTS"


def test_old_database_gets_recipient_columns(tmp_path, monkeypatch):
    import config, store
    db = tmp_path / "old.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE drafts(id INTEGER PRIMARY KEY AUTOINCREMENT, nct_id TEXT, kind TEXT, subject TEXT, body TEXT, status TEXT, created REAL, updated REAL)")
    c.commit(); c.close()
    monkeypatch.setattr(config, "DB_PATH", str(db))
    store.init()
    cols = {r["name"] for r in store.q("PRAGMA table_info(drafts)")}
    assert {"to_name", "to_org", "to_email", "to_role", "to_source"} <= cols


def test_offline_run_addresses_drafts_and_uses_publications(tmp_path, monkeypatch):
    import agent, config, fixtures, notify, store, report
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setattr(config, "REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(notify, "send", lambda message: None)
    assert agent.run("normal", limit=40, llm_mode="mock", verbose=False)["status"] == "COMPLETED"
    ds = store.q("SELECT * FROM drafts")
    assert ds and all(d["to_role"] for d in ds)
    assert all(d["to_email"].endswith("@synthetic.invalid") for d in ds if d["to_email"])
    published = [d for d in ds if "pubmed.ncbi.nlm.nih.gov" in d["body"]]
    assert published and all(d["kind"] == "sex_stratified_results" for d in published)
    assert all(fixtures.SYN_SEX_SENTENCE in d["body"] for d in published)
    labels = {r["label"] for r in store.q("SELECT label FROM verdicts WHERE chk='publication_sex_analysis'")}
    assert {"MENTIONED_IN_PUBLICATION", "NOT_FOUND_IN_ABSTRACTS", "NO_LINKED_PUBLICATION"} <= labels
    assert any(r["% of those gaps where a linked abstract mentions a sex analysis (lead, unverified)"] for r in report.gap_map())
