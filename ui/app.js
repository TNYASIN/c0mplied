(() => {
  "use strict";

  const $ = id => document.getElementById(id);
  const state = {
    scope: "real",
    studies: [],
    overview: null,
    selectedId: null,
    detail: null,
    finding: null,
    mode: "beginner",
    agent: null,
    poll: null,
    lastRunKey: null,
    draftsKey: null,
  };

  function node(tag, className, text) {
    const out = document.createElement(tag);
    if (className) out.className = className;
    if (text != null) out.textContent = text;
    return out;
  }

  async function request(url, options = {}) {
    const response = await fetch(url, { cache: "no-store", ...options });
    let body;
    try { body = await response.json(); } catch (_) { body = {}; }
    if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
    return body;
  }

  function setConnection(online, message) {
    const el = $("connection");
    el.textContent = message || (online ? "Agent connected" : "Agent unavailable");
    el.className = `connection ${online ? "online" : "offline"}`;
  }

  function tag(text, kind = "") {
    return node("span", `tag ${kind}`.trim(), text);
  }

  function findingLabel(study, check) {
    const f = study.findings[check];
    return f && f.trusted ? f.label : null;
  }

  async function loadScope(scope, preserveSelection = false) {
    state.scope = scope;
    $("scope-select").value = scope;
    $("demo-banner").hidden = scope !== "synthetic";
    try {
      const data = await request(`/api/studies?scope=${encodeURIComponent(scope)}`);
      state.studies = data.studies;
      state.overview = data.overview;
      if (!preserveSelection || !state.studies.some(s => s.nct_id === state.selectedId)) {
        state.selectedId = state.studies[0]?.nct_id || null;
        state.detail = null;
        state.finding = null;
      }
      renderOverview();
      renderStudies();
      if (state.selectedId) await selectStudy(state.selectedId, false);
      else renderNoSelection();
    } catch (error) {
      $("empty-data").hidden = false;
      $("empty-data").textContent = `Could not load stored evidence: ${error.message}`;
      setConnection(false);
    }
  }

  function renderOverview() {
    const o = state.overview || { trusted_records: 0, results_not_posted: 0, reporting_gaps: 0, needs_review: 0, conditions: [] };
    $("metric-checked").textContent = o.trusted_records;
    $("metric-no-results").textContent = o.results_not_posted;
    $("metric-gaps").textContent = o.reporting_gaps;
    $("metric-review").textContent = o.needs_review;
    $("empty-data").hidden = state.studies.length > 0;
    $("map-denominator").textContent = `Denominator: ${o.trusted_records} verified ${o.trusted_records === 1 ? "study" : "studies"}`;

    const map = $("condition-map");
    map.replaceChildren();
    if (!o.conditions.length) {
      map.append(node("p", "muted", "No verified condition summary is available yet."));
      return;
    }
    for (const condition of o.conditions) {
      const button = node("button", "condition-row");
      button.type = "button";
      button.setAttribute("aria-label", `Filter studies to ${condition.condition}`);
      button.append(node("strong", "", condition.condition));
      const stack = node("span", "stack");
      const denom = Math.max(condition.checked, 1);
      const gap = node("span", "gap");
      gap.style.width = `${100 * condition.reporting_gaps / denom}%`;
      gap.title = `${condition.reporting_gaps} reporting gaps`;
      const missing = node("span", "missing");
      missing.style.width = `${100 * condition.results_not_posted / denom}%`;
      missing.title = `${condition.results_not_posted} without posted results`;
      const other = node("span", "other");
      other.style.width = `${100 * Math.max(0, condition.checked - condition.reporting_gaps - condition.results_not_posted) / denom}%`;
      other.title = "Other verified reporting status";
      stack.append(gap, missing, other);
      button.append(stack, node("span", "condition-count", `${condition.reporting_gaps} gap · ${condition.results_not_posted} no results · n=${condition.checked}`));
      button.addEventListener("click", () => {
        $("study-search").value = condition.condition;
        renderStudies();
        $("study-list").scrollIntoView({ behavior: "smooth", block: "center" });
      });
      map.append(button);
    }
    const legend = node("div", "legend");
    legend.append(node("span", "", "Reporting gap"), node("span", "l-missing", "Results not posted"), node("span", "l-other", "Other verified status"));
    map.append(legend);
  }

  function renderStudies() {
    const query = $("study-search").value.trim().toLowerCase();
    const studies = state.studies.filter(s => !query || `${s.nct_id} ${s.title} ${s.condition}`.toLowerCase().includes(query));
    const list = $("study-list");
    list.replaceChildren();
    if (!studies.length) {
      list.append(node("p", "muted", state.studies.length ? "No studies match this filter." : "No audited studies are available in this view."));
      return;
    }
    for (const study of studies) {
      const card = node("button", `study-card${study.nct_id === state.selectedId ? " selected" : ""}`);
      card.type = "button";
      card.setAttribute("aria-pressed", study.nct_id === state.selectedId ? "true" : "false");
      card.append(node("span", "id", study.nct_id), node("strong", "", study.title), node("span", "condition", study.condition));
      const tags = node("span", "study-tags");
      const strat = findingLabel(study, "sex_stratified_results");
      if (strat === "NO_RESULTS_POSTED") tags.append(tag("Results not posted", "warn"));
      else if (strat === "NOT_FOUND_IN_RECORD") tags.append(tag("Result by sex not identified", "warn"));
      else if (strat === "STRATIFIED_FOUND") tags.append(tag("Result by sex found", "good"));
      if (study.needs_review) tags.append(tag("Needs review", "bad"));
      if (study.synthetic) tags.append(tag("Synthetic demo"));
      if (!tags.childElementCount) tags.append(tag(`${study.trusted_findings} verified findings`, "good"));
      card.append(tags);
      card.addEventListener("click", () => selectStudy(study.nct_id, true));
      list.append(card);
    }
  }

  async function selectStudy(nctId, scroll) {
    state.selectedId = nctId;
    renderStudies();
    try {
      state.detail = await request(`/api/studies/${encodeURIComponent(nctId)}`);
      state.finding = state.detail.findings.find(f => f.check === "sex_stratified_results") || state.detail.findings[0] || null;
      renderSelectedStudy();
      if (scroll) $("findings").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      $("study-notice").hidden = false;
      $("study-notice").className = "notice error";
      $("study-notice").textContent = `Could not load this study: ${error.message}`;
    }
  }

  function renderNoSelection() {
    state.detail = null;
    state.finding = null;
    $("selected-subtitle").textContent = "Choose a study above to see its evidence.";
    $("study-notice").hidden = true;
    $("finding-tabs").replaceChildren(node("p", "muted", "No study selected."));
    $("finding-detail").replaceChildren(emptyState("Select a finding", "Choose a checked study, then select one of its findings."));
    $("participant-chart").replaceChildren(node("p", "muted", "Select a study with structured baseline counts."));
    $("ask-context").textContent = "No study selected";
  }

  function emptyState(title, body) {
    const wrap = node("div", "empty-state");
    wrap.append(node("span", "", "⌁"), node("h3", "", title), node("p", "", body));
    return wrap;
  }

  function renderSelectedStudy() {
    const d = state.detail;
    $("selected-subtitle").textContent = `${d.nct_id} · ${d.title} · ${d.condition}`;
    $("ask-context").textContent = `Selected: ${d.nct_id}`;
    const notice = $("study-notice");
    notice.hidden = false;
    notice.className = `notice${d.synthetic ? " demo" : ""}`;
    notice.replaceChildren(node("strong", "", d.synthetic ? "Synthetic demo record" : "Source-aware evidence"), node("span", "", d.data_notice));
    if (d.source_url) {
      const link = node("a", "", "Open original NCT record");
      link.href = d.source_url; link.target = "_blank"; link.rel = "noopener noreferrer";
      notice.append(link);
    }
    renderParticipantChart();
    renderFindingTabs();
    renderFinding();
  }

  function renderParticipantChart() {
    const target = $("participant-chart");
    target.replaceChildren();
    const d = state.detail;
    if (!d?.distribution) {
      target.append(node("p", "muted", d ? `No structured female/male baseline counts are stored for ${d.nct_id}.` : "Select a study."));
      return;
    }
    const dist = d.distribution;
    const head = node("div", "distribution-head");
    head.append(node("strong", "", d.nct_id), node("span", "denominator", `Denominator: ${dist.denominator.toLocaleString()} participants`));
    const bar = node("div", "distribution");
    const female = node("span", "female", `${Math.round(100 * dist.female / dist.denominator)}%`);
    female.style.width = `${100 * dist.female / dist.denominator}%`;
    const male = node("span", "male", `${Math.round(100 * dist.male / dist.denominator)}%`);
    male.style.width = `${100 * dist.male / dist.denominator}%`;
    bar.append(female, male);
    const labels = node("div", "distribution-legend");
    const f = node("div"); f.append(node("strong", "", dist.female.toLocaleString()), node("span", "", "Women / female category"));
    const m = node("div"); m.append(node("strong", "", dist.male.toLocaleString()), node("span", "", "Men / male category"));
    labels.append(f, m);
    target.append(head, bar, labels);
  }

  function renderFindingTabs() {
    const tabs = $("finding-tabs");
    tabs.replaceChildren();
    if (!state.detail?.findings.length) {
      tabs.append(node("p", "muted", "No stored findings for this study."));
      return;
    }
    for (const finding of state.detail.findings) {
      const button = node("button", `finding-tab${finding.check === state.finding?.check ? " active" : ""}`);
      button.type = "button";
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", finding.check === state.finding?.check ? "true" : "false");
      button.append(node("strong", "", finding.check_name));
      const line = node("span");
      line.append(node("i", `trust-dot${finding.trusted ? "" : " withheld"}`), document.createTextNode(`${finding.label_name} · ${finding.trusted ? "verified" : "withheld"}`));
      button.append(line);
      button.addEventListener("click", () => { state.finding = finding; renderFindingTabs(); renderFinding(); });
      tabs.append(button);
    }
  }

  function renderFinding() {
    const target = $("finding-detail");
    target.replaceChildren();
    const f = state.finding;
    if (!f) { target.append(emptyState("No finding available", "This study does not have a stored finding to explain.")); return; }
    target.append(node("p", "eyebrow", f.trusted ? "Verified finding" : "Withheld from trusted evidence"), node("h3", "", f.label_name));
    const status = node("div", `notice${f.trusted ? "" : " error"}`);
    status.textContent = f.trusted
      ? "This finding passed verification and is not quarantined. Interpret it only within the registry fields checked."
      : "This finding did not clear verification or was quarantined. It is shown for research review, not as a verified conclusion.";
    target.append(status);
    if (state.mode === "beginner") renderBeginner(target, f);
    else renderResearcher(target, f);
  }

  function renderBeginner(target, finding) {
    const labels = [["What did we find?", "what"], ["Why might this matter?", "why"], ["What evidence supports this?", "evidence"], ["What should someone investigate next?", "next"]];
    const grid = node("div", "explanation-grid");
    for (const [title, key] of labels) {
      const section = node("section");
      section.append(node("h4", "", title), node("p", "", finding.beginner[key]));
      grid.append(section);
    }
    target.append(grid);
  }

  function renderResearcher(target, finding) {
    const r = finding.researcher;
    const fields = [
      ["Original classification", r.classification], ["Source field path", r.source_path],
      ["Audit method", r.method], ["Confidence", r.confidence == null ? "Not stored" : String(r.confidence)],
      ["Run ID", r.run_id || "Not stored"], ["Batch", r.batch == null ? "Not stored" : String(r.batch)],
      ["Verified", r.verified ? "Yes" : "No"], ["Quarantined", r.quarantined ? "Yes" : "No"],
      ["Verification outcome", r.verification_outcome], ["Recorded at", r.recorded_at || "Not stored"],
    ];
    const dl = node("dl", "researcher-grid");
    for (const [name, value] of fields) {
      const wrap = node("div"); wrap.append(node("dt", "", name), node("dd", name.includes("path") || name === "Run ID" ? "mono" : "", value)); dl.append(wrap);
    }
    target.append(dl);
    const quote = node("div", "excerpt");
    quote.append(node("p", "eyebrow", "Original stored excerpt"), node("p", "", r.original_excerpt || "No positive excerpt is stored for this absence or structured-field finding."));
    target.append(quote);
    if (finding.check === "eligibility_exclusion" && state.detail?.eligibility_text) {
      const source = node("details", "source-text");
      source.append(node("summary", "", "Inspect full stored eligibility text"), node("pre", "", state.detail.eligibility_text));
      target.append(source);
    }
  }

  function setMode(mode) {
    state.mode = mode;
    for (const [id, value] of [["beginner-mode", "beginner"], ["researcher-mode", "researcher"]]) {
      const active = mode === value;
      $(id).classList.toggle("active", active);
      $(id).setAttribute("aria-pressed", active ? "true" : "false");
    }
    renderFinding();
  }

  function appendMessage(kind, text, answer = null) {
    const history = $("chat-history");
    const message = node("div", `message ${kind}`);
    if (kind === "user") message.append(node("p", "", text));
    else {
      message.append(node("div", "avatar", "H"));
      const body = node("div"); body.append(node("strong", "", "HerEvidence"), node("p", "", text));
      if (answer) {
        const meta = node("div", "message-meta", answer.scope_note);
        const checked = answer.records_checked.length
          ? `${answer.records_checked.length} record${answer.records_checked.length === 1 ? "" : "s"} checked: ${answer.records_checked.join(", ")}`
          : "No study-specific records were required for this answer.";
        meta.append(node("p", "", checked));
        if (answer.references.length) {
          const refs = node("div", "reference-list");
          for (const ref of answer.references) {
            if (ref.url) {
              const link = node("a", "", ref.nct_id); link.href = ref.url; link.target = "_blank"; link.rel = "noopener noreferrer"; refs.append(link);
            } else refs.append(node("span", "", `${ref.nct_id}${ref.synthetic ? " · synthetic" : ""}`));
          }
          meta.append(refs);
        }
        body.append(meta);
      }
      message.append(body);
    }
    history.append(message);
    history.scrollTop = history.scrollHeight;
    return message;
  }

  async function askQuestion(question) {
    const clean = question.trim();
    if (!clean) return;
    $("ask-error").hidden = true;
    appendMessage("user", clean);
    $("question").value = "";
    $("ask-submit").disabled = true;
    const loading = appendMessage("assistant", "Checking stored evidence");
    loading.querySelector("p").classList.add("typing");
    try {
      const answer = await request("/api/ask", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: clean, nct_id: state.selectedId, scope: state.scope }),
      });
      loading.remove();
      appendMessage("assistant", answer.answer, answer);
    } catch (error) {
      loading.remove();
      $("ask-error").textContent = `I couldn’t check the records: ${error.message}`;
      $("ask-error").hidden = false;
    } finally { $("ask-submit").disabled = false; }
  }

  const draftStatus = {
    DRAFT: ["Waiting", "warn"], APPROVED: ["Approved", "good"],
    REJECTED: ["Rejected", "bad"], RESOLVED: ["Gap closed", "good"],
  };

  function setWorkflowMessage(message, isError = false) {
    const target = $("workflow-message");
    target.hidden = !message;
    target.className = isError ? "form-error" : "notice";
    target.textContent = message || "";
  }

  function renderDrafts(drafts) {
    const key = JSON.stringify(drafts.map(d => [d.id, d.status]));
    if (key === state.draftsKey) return;
    const open = new Set([...document.querySelectorAll("#draft-list details[open]")].map(item => item.dataset.id));
    state.draftsKey = key;
    const list = $("draft-list");
    list.replaceChildren();
    if (!drafts.length) {
      list.append(node("p", "muted", "No follow-up drafts yet. Reporting gaps create approval-gated drafts during an audit."));
      return;
    }
    for (const draft of drafts) {
      const details = node("details", "draft-item");
      details.dataset.id = String(draft.id);
      details.open = open.has(String(draft.id));
      const summary = node("summary");
      const [label, kind] = draftStatus[draft.status] || [draft.status, ""];
      summary.append(tag(label, kind), node("strong", "", draft.subject), node("span", "id", `${draft.nct_id}${draft.source === "synthetic" ? " · demo" : ""}`));
      const body = node("pre", "draft-body", draft.body);
      details.append(summary, body);
      if (draft.status === "DRAFT") {
        const actions = node("div", "draft-actions");
        const approve = node("button", "approve", "Approve draft"); approve.type = "button";
        const reject = node("button", "reject", "Reject draft"); reject.type = "button";
        approve.addEventListener("click", () => updateDraft(draft.id, "APPROVED", approve));
        reject.addEventListener("click", () => updateDraft(draft.id, "REJECTED", reject));
        actions.append(approve, reject); details.append(actions);
      }
      list.append(details);
    }
  }

  async function updateDraft(id, status, button) {
    button.disabled = true;
    setWorkflowMessage("");
    try {
      await request("/api/draft", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, status }),
      });
      state.draftsKey = null;
      setWorkflowMessage(`Draft ${id} marked ${status.toLowerCase()}. Nothing was sent automatically.`);
      await refreshAgent();
    } catch (error) {
      button.disabled = false;
      setWorkflowMessage(`Could not update the draft: ${error.message}`, true);
    }
  }

  async function simulateFollowUp() {
    const button = $("simulate-followup");
    button.disabled = true;
    setWorkflowMessage("Simulating a synthetic registry update and starting re-audit…");
    try {
      const out = await request("/api/followup", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
      });
      $("run-command").textContent = `$ python ${out.started}`;
      setWorkflowMessage(`${out.nct_id} now contains a simulated result-by-sex update. The agent is re-auditing the saved record.`);
      await refreshAgent();
    } catch (error) {
      setWorkflowMessage(`Could not simulate follow-up: ${error.message}`, true);
      button.disabled = false;
    }
  }

  function renderOperations(s) {
    const drafts = s.drafts || [];
    renderDrafts(drafts);
    const canFollow = drafts.some(d => d.source === "synthetic" && d.kind === "sex_stratified_results" && ["DRAFT", "APPROVED"].includes(d.status));
    $("simulate-followup").disabled = Boolean(s.running) || !canFollow;
    $("handoff-report").textContent = s.handoff || "No handoff report yet. Complete or halt a run to create one.";

    const events = $("event-list"); events.replaceChildren();
    if (!s.events?.length) events.append(node("p", "muted", "No events recorded."));
    else for (const event of s.events) {
      const row = node("div", "event-row");
      const time = node("time", "", event.ts ? new Date(event.ts * 1000).toLocaleString() : "Time unavailable");
      const detail = node("span", "", `${String(event.kind || "event").replaceAll("_", " ")}: ${event.detail || ""}`);
      row.append(time, detail); events.append(row);
    }
    renderMeasured(s.measured || {});
  }

  function renderMeasured(measured) {
    const table = $("compare-results"); table.replaceChildren();
    const comparisons = Array.isArray(measured.compare) ? measured.compare : [];
    if (!comparisons.length) {
      const row = node("tr"); const cell = node("td", "muted", "Run compare.py to create measured comparison results.");
      cell.colSpan = 6; row.append(cell); table.append(row);
    } else for (const result of comparisons) {
      const row = node("tr");
      for (const value of [
        result.scenario, result.supervisor ? "On" : "Off", String(result.status || "").replaceAll("_", " ").toLowerCase(),
        `${result.wrong_published} / ${result.published}`, result.withheld, `$${Number(result.cost_usd || 0).toFixed(3)}`,
      ]) row.append(node("td", "", String(value)));
      table.append(row);
    }
    const gold = $("gold-results"); gold.replaceChildren();
    if (!measured.gold) {
      gold.append(node("p", "muted", "No hand-labelled gold-set result is saved yet."));
      return;
    }
    gold.append(node("p", "eyebrow", `Gold set · n=${measured.gold.n}`));
    for (const [name, value] of Object.entries(measured.gold.accuracy || {})) {
      const metric = node("div", "gold-metric");
      const shown = typeof value === "number" && value <= 1 ? `${Math.round(value * 100)}%` : String(value);
      metric.append(node("strong", "", shown), node("span", "", name.replaceAll("_", " "))); gold.append(metric);
    }
  }

  function renderAgent(s) {
    state.agent = s;
    const run = s.run, snap = s.snapshot, counts = s.counts || {};
    const pill = $("run-pill");
    if (s.running) { pill.className = "status-pill running"; pill.textContent = `Running · ${run?.scenario || "audit"}`; }
    else if (!run) { pill.className = "status-pill idle"; pill.textContent = "Idle"; }
    else if (run.status === "COMPLETED") { pill.className = "status-pill done"; pill.textContent = "Completed"; }
    else { pill.className = "status-pill halted"; pill.textContent = `Halted · ${(run.halt_code || run.status).replaceAll("_", " ")}`; }
    document.querySelectorAll("[data-scenario]").forEach(button => button.disabled = s.running);
    $("resume-run").disabled = s.running;
    $("run-audited").textContent = counts.audited || 0;
    $("run-calls").textContent = (snap?.calls || 0).toLocaleString();
    $("run-tokens").textContent = (snap?.tokens || 0).toLocaleString();
    $("run-drafts").textContent = counts.drafts || 0;
    const alert = $("agent-alert");
    if (run?.halt_code) {
      alert.hidden = false; alert.className = "notice error";
      alert.textContent = `The supervisor stopped the run: ${run.halt_reason}. ${s.advice || ""}`;
    } else if (run?.status === "COMPLETED") {
      alert.hidden = false; alert.className = "notice";
      alert.textContent = `Audit completed. ${counts.drafts || 0} approval-gated draft${counts.drafts === 1 ? " is" : "s are"} waiting; nothing is sent automatically.`;
    } else alert.hidden = true;

    const limit = snap?.limits;
    renderGuard("ground", snap?.trackers?.grounding, limit);
    renderGuard("recheck", snap?.trackers?.recheck, limit);
    const use = limit ? Math.max((snap.tokens || 0) / limit.max_tokens, (snap.calls || 0) / limit.max_calls, (snap.cost || 0) / limit.max_cost_usd) : 0;
    $("guard-budget").textContent = `${Math.round(100 * use)}%`;
    $("bar-budget").style.width = `${Math.min(100, 100 * use)}%`;
    const queue = counts.queue || {};
    $("queue-summary").textContent = Object.keys(queue).length ? Object.entries(queue).map(([k, v]) => `${k}: ${v}`).join(" · ") : "Queue empty";
    const recent = $("recent-list"); recent.replaceChildren();
    if (!s.recent?.length) recent.append(node("p", "muted", "Nothing audited yet."));
    else for (const record of s.recent) {
      const row = node("div", "recent-row"); row.append(node("span", "id", record.nct_id), node("span", "", record.condition || "Condition not recorded"));
      const tags = node("span", "study-tags");
      if (record.quarantined) tags.append(tag("Set aside", "bad"));
      if (record.rejected) tags.append(tag(`${record.rejected} rejected`, "bad"));
      if (!record.quarantined && !record.rejected) tags.append(tag("Checked", "good"));
      row.append(tags); recent.append(row);
    }
    renderOperations(s);
  }

  function renderGuard(id, tracker, limits) {
    if (!tracker || !limits) { $("guard-" + id).textContent = "Not started"; $("bar-" + id).style.width = "0"; return; }
    const p = Number(tracker.p_exceeds || 0);
    $("guard-" + id).textContent = `${tracker.errors}/${tracker.n} errors · P ${p.toFixed(2)}`;
    $("bar-" + id).style.width = `${Math.min(100, 100 * p)}%`;
    $("bar-" + id).style.background = p >= limits.halt_probability ? "var(--danger)" : p >= limits.halt_probability * .6 ? "#cf9861" : "var(--forest-2)";
  }

  async function refreshAgent() {
    clearTimeout(state.poll);
    try {
      const s = await request("/api/state");
      setConnection(true);
      const key = s.run ? `${s.run.run_id}|${s.run.status}` : "none";
      const completedNewRun = state.lastRunKey && key !== state.lastRunKey && !s.running;
      state.lastRunKey = key;
      renderAgent(s);
      if (completedNewRun) await loadScope(state.scope, true);
      state.poll = setTimeout(refreshAgent, s.running ? 900 : 4000);
      return s;
    } catch (error) {
      setConnection(false, "Agent unavailable");
      $("run-command").textContent = `Start ui_server.py and reload. ${error.message}`;
      state.poll = setTimeout(refreshAgent, 5000);
      return null;
    }
  }

  async function startRun(scenario, resume = false) {
    const live = $("run-data").value === "live";
    $("run-command").textContent = "Starting the audit…";
    try {
      const out = await request("/api/run", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario, live, resume }),
      });
      $("run-command").textContent = `$ python ${out.started}`;
      await refreshAgent();
    } catch (error) { $("run-command").textContent = `Could not start: ${error.message}`; }
  }

  function bindEvents() {
    $("scope-select").addEventListener("change", event => loadScope(event.target.value));
    $("study-search").addEventListener("input", renderStudies);
    $("beginner-mode").addEventListener("click", () => setMode("beginner"));
    $("researcher-mode").addEventListener("click", () => setMode("researcher"));
    $("ask-form").addEventListener("submit", event => { event.preventDefault(); askQuestion($("question").value); });
    $("question").addEventListener("keydown", event => {
      if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); $("ask-form").requestSubmit(); }
    });
    document.querySelectorAll(".suggestions button").forEach(button => button.addEventListener("click", () => askQuestion(button.textContent)));
    document.querySelectorAll("[data-scenario]").forEach(button => button.addEventListener("click", () => startRun(button.dataset.scenario)));
    $("resume-run").addEventListener("click", () => startRun("normal", true));
    $("simulate-followup").addEventListener("click", simulateFollowUp);
  }

  async function init() {
    bindEvents();
    const agent = await refreshAgent();
    let initial = "real";
    if (agent && !agent.data_available.real && agent.data_available.synthetic) initial = "synthetic";
    await loadScope(initial);
  }

  init();
})();
