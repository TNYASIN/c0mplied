HerEvidence Real-Record Labeling Manual (v1, hackathon)
Labeling Unit and Boundaries

The unit is a frozen JSON version of one ClinicalTrials.gov v2 registry record, not a paper, a study protocol, or all the analyses the investigators actually performed. Each record has its NCT ID, retrieval time, last update date, and SHA-256 in data/real_gold/manifest.json. A label only describes what is visible in that JSON. The official site divides posted summary results into modules such as participant flow, baseline characteristics, outcome measures, and adverse events. This project’s “outcomes by sex” check evaluates only the outcomeMeasuresModule, and does not treat baseline counts or adverse event tables as outcome analyses.

Official definition references: Study Basics, Outcome Measure Data Preparation Checklist, Results Data Element Definitions. The classification thresholds below are the project’s operational definitions for research purposes, not an official ClinicalTrials.gov rating.

Four Check Items
1. sex_restriction

Read protocolSection.eligibilityModule.sex and label it with the original value: ALL, FEMALE, MALE, or UNKNOWN. It only represents the sex field registered for enrollment and does not infer fairness. The field path and value must be saved.

2. eligibility_exclusion

Read the inclusion and exclusion criteria in protocolSection.eligibilityModule.eligibilityCriteria in full, and assign one primary label for the study as a whole:

Label	Criterion	What cannot be labeled this way
BLANKET_EXCLUSION_CHILDBEARING	Explicitly excludes all women of childbearing potential, with no other study arm allowing them to participate; also includes an explicit restriction to enrolling only women who cannot bear children	Excluding only pregnant women; only requiring contraception; excluding in one treatment arm while another arm allows them
PREGNANCY_LACTATION_EXCLUSION	Pregnant, breastfeeding, or pregnancy-test-positive people may not participate, even if it is written in the inclusion criteria as a “not pregnant” condition	Only requiring a pregnancy test, without stating that positive results cannot participate and with no way to infer it from context
CONDITIONAL	People of childbearing potential may participate under conditions such as contraception or pregnancy testing, with no stronger overall exclusion	Everyone is excluded without exception
NONE	After reading the entire field, none of the above restrictions are present	The field is missing, unreadable, or only keyword fragments were reviewed
UNCLEAR	The field is missing, vague, or self-contradictory, or the current single-label scheme cannot express an exclusion specific to one study arm	Simply having no posted results

If a record has both an explicit overall pregnancy/lactation exclusion and a contraception condition, the primary label is PREGNANCY_LACTATION_EXCLUSION, and the coexisting condition is noted in the remarks. An overall blanket exclusion takes precedence over other labels. For a record that restricts only one study arm while other arms still allow women of childbearing potential, label it UNCLEAR first and keep both conflicting pieces of evidence. The next version can switch to multi-label and arm-level labeling. These labels do not evaluate whether a restriction is medically reasonable.

A positive label must provide a short quote from the original text and its JSON path. NONE must record the full field path that was read through.

3. enrollment_by_sex

If the top-level hasResults=false, label it NO_RESULTS_POSTED. Otherwise, review resultsSection.baselineCharacteristicsModule.measures: label it REPORTED only when you see a baseline category corresponding to sex/gender identity and at least one actual count value. If there is only a “Sex: Female, Male” title with no measurements[].value, label it NOT_REPORTED_IN_RECORD. Do not count outcome or participant flow numbers. Record the measure path, the category, and one actual value. A single-sex trial can also be REPORTED as long as the values are actually visible.

4. sex_stratified_results

If hasResults=false, label it NO_RESULTS_POSTED. Otherwise, review all of resultsSection.outcomeMeasuresModule.outcomeMeasures, including each outcome’s title, description, groups, classes/categories/measurements, and analyses:

Label	Criterion
STRATIFIED_FOUND	In at least one posted outcome, the result values can be clearly matched to women and to men/other explicit sex/gender subgroups. This can be sex-named outcome groups, or sex-named classes/categories with values. The outcome index, group names, and corresponding values must be saved. A statistical analysis plan or text saying “will be analyzed by sex” is not enough.
NOT_FOUND_IN_RECORD	Results are posted, but after reviewing the outcome module one by one, no such structure was found. Mentioning male and female participants, sexual function scales, baseline counts, randomization stratified by sex, or group names without values is not enough.
UNCLEAR	The structure is incomplete, or the relationship between text and values cannot be determined.
NO_RESULTS_POSTED	hasResults=false.

This definition answers the key question: sex-named groups alone are not enough; there must be corresponding outcome values. STRATIFIED_FOUND does not mean there was a formal statistical test for sex interaction, nor does it mean the study proved that efficacy differs between men and women.

Two-Person Labeling and Conflict Adjudication

Two labelers independently review the frozen JSON without looking at model predictions. Each fills in the four labels, evidence paths, short quotes, outcome values or “search scope,” and remarks. First compute per-item agreement rates and Cohen’s kappa. For disagreements, review the same SHA-256 version together and adjudicate according to the tables above. If they still disagree, a third person adjudicates. Before adjudication, keep both people’s original labels and reasons, and do not silently overwrite them. If the labeling scheme itself cannot express a record, keep UNCLEAR and log it as a rule-revision case.

The current data/gold_set.json is Codex single-reviewer initial labels and has not yet been reviewed by a second human labeler. It can be used to find code problems and demonstrate metric computation, but it cannot be described externally as “human-consensus gold” or real accuracy. Within three hours, the team’s second person can prioritize reviewing all positives, UNCLEAR cases, and records where the model disagrees with the initial labels.

Evaluation Conventions

In the confusion matrix, rows are ground truth and columns are predictions. For each label, precision = TP/(TP+FP) and recall = TP/(TP+FN). When a denominator is zero, display null; do not disguise it as 0. UNCLEAR is an active abstention, and abstention rate = predicted UNCLEAR / all records for that check item. NO_RESULTS_POSTED is a valid label and does not count as abstention. Report overall accuracy on all records, accuracy on non-abstained records, coverage, and the support of each label. Challenge samples were deliberately added, so this set cannot be used to estimate the true prevalence of any type of gap across all trials.