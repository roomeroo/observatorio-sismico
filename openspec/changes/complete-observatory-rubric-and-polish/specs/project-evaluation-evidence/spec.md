## ADDED Requirements

### Requirement: Deliver the evaluation memoir and acceptance evidence

The repository MUST contain, under `docs/`: a data dictionary with query provenance; a quality analysis covering completeness, uniqueness, validity, consistency, timeliness and accuracy with SQL/code, before/after counts, decisions and sample records; conceptual, logical and physical models with grain, keys and index justification; a complexity report with at least three input sizes (synthetic data labeled and excluded from analysis), time and memory measurements, sequential versus indexed comparison and a 100-million-row reasoning; a cost and scaling section; at least three numeric conclusions with filters and period; and an acceptance matrix for the eleven tests of the statement with evidence for each.

#### Scenario: Quality evidence is reproducible

- **GIVEN** the quality section
- **WHEN** its queries are run on the database
- **THEN** they reproduce the reported figures

#### Scenario: Acceptance matrix is complete

- **GIVEN** the acceptance matrix
- **WHEN** it is reviewed
- **THEN** each of the eleven tests lists steps, expected result, observed result and evidence

#### Scenario: Synthetic benchmark data is separated

- **GIVEN** replicated data for scale tests
- **WHEN** analysis queries run
- **THEN** synthetic rows are excluded and identifiable
