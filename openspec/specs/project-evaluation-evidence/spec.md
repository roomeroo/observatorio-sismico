# Project Evaluation Evidence

## Purpose

Define the measurable evidence expected for the project's performance, complexity, cost, and five rubric dimensions.

## Requirements

### Requirement: [NF-08] Measure complexity, time, memory, and costs

Evidence MUST analyze identifier lookup, geographic integration, and window aggregation; distinguish average/worst-case complexity where applicable; and measure time/memory at three input sizes with equipment and method. Label synthetic scale data; discuss cost categories, limits, and scaling assumptions.

Priority: Explicitly required as a project deliverable.
Traceability: `ENUNCIADO (1).md` §10, §12; `FAQ.md` Q33–35.

#### Scenario: Performance evidence is reviewed

- **GIVEN** performance measurements are submitted
- **WHEN** the evidence is evaluated
- **THEN** it includes at least three input sizes, time and memory results, equipment, and procedure
- **AND** identifies synthetic scale data separately from real seismic data

#### Scenario: Complexity and cost claims are reviewed

- **GIVEN** the report explains implementation complexity and costs
- **WHEN** its claims are evaluated
- **THEN** it discusses the three required operations, applicable average/worst cases, cost categories, assumptions, and a scaling proposal
- **AND** does not present an unmeasured benefit or an assumed free cloud tier as verified zero total cost
- **AND** identifies hardware, electricity, storage, transfer, maintenance, and development time

### Requirement: Preserve the five rubric dimensions and their stated levels

Evidence MUST address the five source rubric dimensions and preserve its bands (0–4, 5–6, 7–8, 9–10). Notable quality means four or more dimensions; Outstanding quality means complete analysis with actions. Notable analysis means three or more analyses; Outstanding adds insights. Do not infer unspecified criterion weights.

Priority: Source-defined evaluation criteria.
Traceability: `docs/ENUNCIADO (1).md` §1, §13; `docs/FAQ.md` Q17, Q34.

#### Scenario: Rubric evidence is assembled

- **GIVEN** the project report and defense materials are evaluated
- **WHEN** each rubric dimension is reviewed
- **THEN** extraction, quality, modeling, analysis, and reflection evidence can be identified against the stated source levels
- **AND** no new weighting or project-specific percentage is claimed

#### Scenario: Quality and analysis levels are distinguished

- **GIVEN** quality and analysis evidence is assessed
- **WHEN** a level is assigned
- **THEN** the source criteria for four or more quality dimensions at Notable and complete analysis with actions at Outstanding are respected
- **AND** three or more analyses at Notable and analysis with insights at Outstanding are respected

## Clarifications Pending

- The documentation does not define individual weights for the five project rubric criteria; only the general published assessment proportions are stated. Do not invent criterion weights.
- The evaluation date, individual/team modality, and mapping to assessment parts are to be communicated in class.
