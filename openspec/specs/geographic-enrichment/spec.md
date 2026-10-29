# Geographic Enrichment

## Purpose

Define how event locations are enriched from the supplied Natural Earth country catalog and how unmapped or ambiguous locations are represented.

## Requirements

### Requirement: [F-07] Assign country attributes by spatial containment

The consumer MUST enrich events spatially against the supplied Natural Earth catalog in compatible WGS84/EPSG:4326 coordinates, not from `place` or nearest-country inference. Check `ADM0_A3` uniqueness; unmatched events remain unassigned.

Priority: Required; boundary rule must be documented.
Traceability: `ENUNCIADO (1).md` §4.3, §7; `FAQ.md` Q18–20; `FUENTES-Y-LICENCIAS (1).md`, catalog.

#### Scenario: Event lies within one catalog polygon

- **GIVEN** an event has valid longitude and latitude and its point is contained by one catalog polygon
- **WHEN** the event is enriched
- **THEN** its country identifier and available catalog attributes are attached using that polygon

#### Scenario: Event lies in the ocean or outside catalog coverage

- **GIVEN** a valid event point is not contained by a catalog polygon
- **WHEN** the event is enriched
- **THEN** the event remains stored with a null country assignment
- **AND** it is represented as “Sin país asignado”, not as an invalid event solely because it is offshore

#### Scenario: Event is on a boundary or matches multiple polygons

- **GIVEN** a point lies on a polygon boundary or produces multiple polygon matches
- **WHEN** country enrichment is performed
- **THEN** the chosen handling rule is documented
- **AND** the result does not claim greater geographic precision than the simplified catalog supports

#### Scenario: Catalog identifier is inspected

- **GIVEN** the supplied catalog is loaded for enrichment
- **WHEN** its country identifier is used
- **THEN** uniqueness of `ADM0_A3` is checked
- **AND** its provenance and non-ISO caveat remain documented

## Clarifications Pending

- The required tie-breaking or null-assignment rule for boundary points and multiple polygon matches is not specified.
- The supplied catalog is simplified, omits some territories, and is not suitable for legal boundaries or precise coastal attribution; these are source limitations, not requirements to correct the catalog.
