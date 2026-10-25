# Gold-set evaluation

- Backend: `mock`
- Records: 25
- Reference status: ['single_reviewer_provisional']
- Confusion matrix: rows = reference, columns = prediction.
- Targeted challenge cases are included; this is not a prevalence estimate.

## sex_restriction

Accuracy: 100.0%; coverage: 100.0%; abstention: 0.0%; non-abstained accuracy: 100.0%

| Label | Support | Predicted | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|
| ALL | 24 | 24 | 100.0% | 100.0% | 100.0% |
| FEMALE | 1 | 1 | 100.0% | 100.0% | 100.0% |
| MALE | 0 | 0 | — | — | — |
| UNKNOWN | 0 | 0 | — | — | — |

Confusion matrix:

| Reference \ Prediction | ALL | FEMALE | MALE | UNKNOWN |
|---|---:|---:|---:|---:|
| ALL | 24 | 0 | 0 | 0 |
| FEMALE | 0 | 1 | 0 | 0 |
| MALE | 0 | 0 | 0 | 0 |
| UNKNOWN | 0 | 0 | 0 | 0 |

## eligibility

Accuracy: 100.0%; coverage: 96.0%; abstention: 4.0%; non-abstained accuracy: 100.0%

| Label | Support | Predicted | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|
| BLANKET_EXCLUSION_CHILDBEARING | 2 | 2 | 100.0% | 100.0% | 100.0% |
| PREGNANCY_LACTATION_EXCLUSION | 9 | 9 | 100.0% | 100.0% | 100.0% |
| CONDITIONAL | 4 | 4 | 100.0% | 100.0% | 100.0% |
| NONE | 9 | 9 | 100.0% | 100.0% | 100.0% |
| UNCLEAR | 1 | 1 | 100.0% | 100.0% | 100.0% |

Confusion matrix:

| Reference \ Prediction | BLANKET_EXCLUSION_CHILDBEARING | PREGNANCY_LACTATION_EXCLUSION | CONDITIONAL | NONE | UNCLEAR |
|---|---:|---:|---:|---:|---:|
| BLANKET_EXCLUSION_CHILDBEARING | 2 | 0 | 0 | 0 | 0 |
| PREGNANCY_LACTATION_EXCLUSION | 0 | 9 | 0 | 0 | 0 |
| CONDITIONAL | 0 | 0 | 4 | 0 | 0 |
| NONE | 0 | 0 | 0 | 9 | 0 |
| UNCLEAR | 0 | 0 | 0 | 0 | 1 |

## enrollment_by_sex

Accuracy: 100.0%; coverage: 100.0%; abstention: 0.0%; non-abstained accuracy: 100.0%

| Label | Support | Predicted | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|
| REPORTED | 19 | 19 | 100.0% | 100.0% | 100.0% |
| NOT_REPORTED_IN_RECORD | 1 | 1 | 100.0% | 100.0% | 100.0% |
| NO_RESULTS_POSTED | 5 | 5 | 100.0% | 100.0% | 100.0% |

Confusion matrix:

| Reference \ Prediction | REPORTED | NOT_REPORTED_IN_RECORD | NO_RESULTS_POSTED |
|---|---:|---:|---:|
| REPORTED | 19 | 0 | 0 |
| NOT_REPORTED_IN_RECORD | 0 | 1 | 0 |
| NO_RESULTS_POSTED | 0 | 0 | 5 |

## sex_stratified

Accuracy: 100.0%; coverage: 100.0%; abstention: 0.0%; non-abstained accuracy: 100.0%

| Label | Support | Predicted | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|
| STRATIFIED_FOUND | 2 | 2 | 100.0% | 100.0% | 100.0% |
| NOT_FOUND_IN_RECORD | 18 | 18 | 100.0% | 100.0% | 100.0% |
| NO_RESULTS_POSTED | 5 | 5 | 100.0% | 100.0% | 100.0% |
| UNCLEAR | 0 | 0 | — | — | — |

Confusion matrix:

| Reference \ Prediction | STRATIFIED_FOUND | NOT_FOUND_IN_RECORD | NO_RESULTS_POSTED | UNCLEAR |
|---|---:|---:|---:|---:|
| STRATIFIED_FOUND | 2 | 0 | 0 | 0 |
| NOT_FOUND_IN_RECORD | 0 | 18 | 0 | 0 |
| NO_RESULTS_POSTED | 0 | 0 | 5 | 0 |
| UNCLEAR | 0 | 0 | 0 | 0 |

## Disagreements


## Publication cross-check (PubMed abstracts)

Linked-publication sentences that appear to report a finding by sex. These are unlabeled leads for a human reader, not scored; a lead on a `NOT_FOUND_IN_RECORD` record means the paper may hold what the registry lacks.

- NCT00043550 (registry reference `NOT_FOUND_IN_RECORD`) PMID 22152401: "Gender and minority status moderated outcome (P = .014), with psychotherapy more efficacious for minority men than MED (P = .027, Cohen d = 1.02) and PBO (P = .019, d = 1.09)."
- NCT00381303 (registry reference `STRATIFIED_FOUND`) PMID 23092052: "Darunavir/ritonavir treatment is safe and effective in treatment-experienced patients, irrespective of sex or race."
