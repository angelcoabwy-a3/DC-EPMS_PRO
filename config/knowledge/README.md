# DC-EPMS PRO - Knowledge Corpus

This directory contains the source documents ingested by the GraphRAG
subsystem (Sprint S2). Each document carries YAML frontmatter that
declares:

- `id`: stable identifier used as the knowledge graph node id
- `title`: human-readable
- `source`, `source_type`: provenance and category
- `applies_to`: list of component types this doc governs
- `tags`: facets for filtering
- `jurisdiction`: geographic applicability
- `version`: doc version (used for invalidation)
- `voltage_class`: LVDC/MVDC/MVAC/etc.

The graphrag_index.py module parses these files at boot (or on first
query, in lazy mode), builds an embedding index over chunks, and links
each document to component types in the site model graph via the
`applies_to` declaration.

## Current Corpus (Sprint S2)

| File | Type | Jurisdiction | Voltage |
|------|------|--------------|---------|
| nvidia-800vdc-architecture.md | vendor_whitepaper | international | LVDC |
| ocp-lvdc-power-distribution.md | industry_specification | international | LVDC |
| stmicro-bms-design.md | vendor_whitepaper | international | LVDC |
| csa-z462-24-stub.md | regulatory_standard | canada | ALL |
| oesc-ontario-stub.md | regulatory_standard | ontario_canada | ALL |

## Adding new knowledge

To add a document, drop a `.md` file with a complete frontmatter into
this directory. Restart the server (or re-issue an `/api/graph/reindex`
admin call - reindex endpoint planned for S5).

## Compliance and Copyright

Vendor whitepapers (NVIDIA, STMicro) are reproduced from publicly
available sources for technical reference within this private R&D
project (a3semi internal). They are NOT redistributed.

Regulatory standards (CSA Z462-24, OESC) are referenced as STUBS
ONLY - we do not reproduce the licensed content. Cite this codebase's
references to procurement URLs (csagroup.org, esasafe.com) for the
authoritative documents.
