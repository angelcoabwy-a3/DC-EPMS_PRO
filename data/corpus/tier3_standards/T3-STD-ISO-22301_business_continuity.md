---
doc_id: T3-STD-ISO-22301
tier: 3
priority: medium
domain: business_continuity
standard: ISO 22301, NFPA 110
applies_to: [business_continuity, rto_rpo, generator_systems, bcdr]
keywords: [iso_22301, business_continuity, rto, rpo, nfpa_110, generator, backup_power]
facility: A3-Alpha Toronto Area
---

# ISO 22301 Business Continuity + NFPA 110 Emergency Power

Source: ISO 22301:2019 (Security and resilience — Business continuity
management systems), NFPA 110:2022 (Standard for Emergency and Standby
Power Systems)

## ISO 22301 — A3-Alpha classification

A3-Alpha Toronto Area is classified as:
- **Priority 1 (P1)**: mission-critical service delivery
- **RTO (Recovery Time Objective)**: 15 minutes maximum downtime
- **RPO (Recovery Point Objective)**: 0 (zero data loss tolerance)
- **MTO (Maximum Tolerable Outage)**: 1 hour
- **MBCO (Minimum Business Continuity Objective)**: 80% IT load within
  30 minutes

### What these targets mean operationally

- Any incident causing >15 min outage triggers P1 review
- Zero data loss requires synchronous replication or equivalent
- One-hour absolute ceiling — customer contracts specify penalties
  beyond this
- Minimum 80% load recovery required even during partial failures

## BCDR (Business Continuity and Disaster Recovery) framework

a3semi maintains documented continuity for:

### Infrastructure BCDR

- Tier IV 2N design (concurrent maintainability)
- Redundant cooling (N+1 chillers, dual DLC manifolds)
- Redundant power (2N UPS, dual utility feed, generator backup)
- Multiple network paths (redundant ISP, dark fiber, satellite emergency)

### Data BCDR

- Synchronous replication to secondary data center (Montreal)
- Asynchronous replication to tertiary (Vancouver)
- Backup retention: 7 days hourly, 30 days daily, 1 year monthly
- Tabletop BCDR exercises quarterly

### People BCDR

- 24/7 NOC staffing with 2 operators minimum
- Cross-training so any operator can run any shift
- Succession plan documented
- Emergency call tree (updated quarterly)

## NFPA 110 — generator systems

A3-Alpha uses Type 10 Level 1 generators per NFPA 110 — the most
stringent classification.

### Type 10: "10 seconds" — acceptance time

From utility loss to full emergency power must occur within 10 seconds.
This is critical because:
- UPS batteries provide 10 minutes (not infinite)
- Generator MUST carry the load well before batteries depleted
- Buffer for generator failure (second-attempt start)

### Level 1: life-safety mission-critical

Level 1 systems provide:
- Fire pumps and fire alarm
- Emergency lighting
- Life-safety elevators
- Essential communications
- Data center IT load (a3semi)

### A3-Alpha generator specifications

- 2 × Caterpillar 3516C diesel generators
- 2.5 MW each (5 MW total capacity)
- Configuration: N+1 (one generator sized for full facility load,
  second as backup)
- Fuel: ULSD (ultra-low sulfur diesel), on-site 72-hour capacity
- Fuel treatment: annual polishing, biocide injection quarterly
- Starting: dual-redundant 24V battery system, each bank
  sized for 10 start attempts

### Start sequence

t=0: Utility loss detected by automatic transfer switch (ATS)
t+0.1s: ATS signals generator to start
t+0.3s: First start attempt begins
t+2-5s: Generator at rated voltage and frequency
t+8s: ATS transfers to generator position
t+10s: Load is on generator (NFPA 110 Type 10 complete)

If first generator fails to start:
t+10s: Second generator starts (redundancy)
t+20s: Second generator carries load (delayed but recoverable)
If both fail: UPS provides up to 15 minutes for orderly shutdown

## Transfer switch operation

Automatic Transfer Switch (ATS) at A3-Alpha:

- 4000A rated, bypass-isolation configuration
- Makes utility/generator transfer within 10 seconds
- Manual bypass for ATS maintenance without interrupting load
- Programmable logic controller (PLC) with fault tolerance
- Dual-redundant controls (no single point of failure)

## Testing schedule per NFPA 110

### Weekly

- Generator run (no-load, 30 minutes minimum)
- Verify start sequence, annunciator panel, battery charger
- Log in `procedures` table (type=GEN_WEEKLY)

### Monthly

- Exercise load-band test (load transfer 30% + generator run)
- Verify ATS transfer both ways
- Exercise voltage regulator, governor, alarms
- Log and archive

### Annual (most stringent)

- Full-load test: 4 hours at rated load (via resistive load bank)
- Documented temperatures, pressures, voltages, frequencies
- Fuel system check: day tank pressure, bulk tank quality sample
- Starting battery capacity test
- Control system comprehensive check

### Quarterly

- Load-band exercise (not just no-load)
- Fuel polishing and biocide check
- Transfer switch exercise (both directions)
- NFPA 110 §8.4 full documentation

## Fuel management

72-hour fuel supply requires active management:

### Bulk tank (20,000 L, above-ground)

- Quarterly fuel sample analysis: water, sediment, biological growth
- Annual polishing (return tank fuel through filter/centrifuge)
- Biocide injection quarterly (dose per fuel volume)
- Fuel age: replace oldest 25% per year (full turnover in 4 years)

### Day tank (500 L, adjacent to generator)

- Auto-refill from bulk tank
- Sight glass check weekly
- Filter replacement semi-annually
- Contamination check monthly

### Fuel delivery in emergency

Pre-established contracts with two fuel suppliers:
- Primary: 4-hour delivery SLA
- Secondary: 8-hour delivery SLA
- Both deliver during declared emergencies (Ontario priority list)

## Incident response integration

When generator activation occurs (regardless of cause):

1. EPMS logs incident with source=GEN_ACTIVATION
2. Severity determination:
   - Normal testing: info
   - Utility outage: warning
   - Generator start failure: critical
3. ISO 22301 P1 clock starts if service impact
4. Post-incident review within 48 hours for any P1

## BCDR exercises — quarterly requirement

ISO 22301 requires documented exercises. A3-Alpha schedule:

### Q1 — Tabletop exercise

- Scenario: "chiller A fails during peak summer"
- Walk through response with NOC team and management
- Identify gaps in procedures or skills
- Document lessons learned

### Q2 — Functional exercise

- Actual failover of one service (not full facility)
- Example: Gemini ER 1.6 robot control transfer to backup
- Real response, measured RTO
- Compare to target, improve

### Q3 — Partial simulation

- Simulate utility loss to generator
- Actual transfer to generator power
- Run on generator for 30 minutes
- Transfer back to utility

### Q4 — Full-scale exercise

- End-to-end BCDR scenario
- Include personnel (evacuation, recall)
- Test communication tree
- External parties (fuel suppliers, customers) participate where
  possible

## Documentation

Every BCDR event (test, actual, exercise) generates:

- Signed test report (regulatory requirement)
- Entry in `procedures` with complete metrics
- Lessons learned document
- Updated procedures if gaps identified
- Customer notification if service impact occurred

## Regulatory compliance

A3-Alpha complies with:

- Ontario Fire Code for emergency power
- Canadian Electrical Code Section 46 for emergency systems
- Ministry of Environment emissions reporting for generators
- Customer contract SLAs (penalty clauses beyond RTO)

## References

- ISO 22301:2019 (Security and resilience — Business continuity)
- NFPA 110:2022 (Emergency and Standby Power Systems)
- NFPA 111:2022 (Stored Electrical Energy Emergency and Standby Power)
- CSA C282-19 (Emergency Electrical Power Supply for Buildings)
- Uptime Institute Tier Standard: Topology (Tier IV 2N)
- a3semi BCDR Plan: A3-BUS-PLN-001 (current rev: 2025.Q3)
- a3semi Annual BCDR Exercise Report: archived in `procedures`
