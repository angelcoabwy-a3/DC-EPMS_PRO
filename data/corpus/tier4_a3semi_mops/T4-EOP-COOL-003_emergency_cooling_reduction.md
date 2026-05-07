---
doc_id: T4-EOP-COOL-003
tier: 4
priority: critical
doc_type: EOP
domain: emergency_operations
applies_to: [cooling_failure, chiller_trip, emergency_response]
standard_refs: [ASHRAE A2, ISO 22301 P1, a3semi BCDR]
keywords: [eop, emergency_cooling, chiller_trip, load_shedding, workload_migration]
facility: A3-Alpha Toronto Area
duration: immediate, sustained until resolved
personnel_required: NOC + facility engineer on-call
---

# EOP-003: Emergency Cooling Reduction Response

**Procedure ID**: T4-EOP-COOL-003
**Revision**: 2026.1
**Activation trigger**: Cooling capacity reduced >30% from normal
**Classification**: P1 (ISO 22301)

## Purpose

Structured response to cooling capacity loss at A3-Alpha Toronto Area.
Maintains ASHRAE A2 compliance, protects IT equipment, and coordinates
load reduction with IT operations.

## Activation conditions

EOP-003 activates when ANY of:

1. Chiller 1 OR Chiller 2 trips (N+1 degraded to N)
2. Both chillers report capacity <70% of demand
3. CRAH airflow loss >30% in any hall
4. DLC loop flow <30 L/min sustained at >5 racks
5. Hall inlet temperature trending to 28°C with positive rate
6. EPMS predictive model forecasts >32°C in 90 seconds

Multiple simultaneous triggers escalate to P1 immediately.

## Response sequence (time-critical)

### t=0 to t+30s: DETECT and VERIFY

**NOC primary actions:**

1. Confirm trigger via EPMS alerts
2. Visual verification on chiller panel(s) and HVAC SCADA
3. Declare incident in PostgreSQL: severity=critical, source=COOLING
4. Page facility engineer on-call (automated)
5. Start incident timeline log

**Physical verification (if safe):**
- Check chiller room for any abnormal sound, smell, visible issue
- Note the status of visible equipment

### t+30s to t+2min: ASSESS

**Determine severity tier:**

| Tier | Condition | Time to A2 critical |
|------|-----------|---------------------|
| A | Single chiller trip, N+1 degraded | >30 minutes (safe margin) |
| B | Both chillers degraded capacity | 5-30 minutes |
| C | Total cooling loss (unlikely) | <44 seconds |

**For Tier A (common case):**
- Remaining chiller ramps to 100% automatically
- Monitor hall temperature trend
- Diagnose failed chiller for restart
- No IT load reduction typically required

**For Tier B:**
- IT workload migration initiated (see below)
- Reduce non-essential workloads
- Pre-alert customer operations teams

**For Tier C:**
- EOP escalates to EOP-001 (emergency shutdown preparation)
- IT workload migration mandatory
- Engage EPO consideration if temperature >33°C

### t+2min to t+5min: ACT

**Tier A response (single chiller trip)**

1. Operator attempts restart of failed chiller:
   - Clear alarms on Smart Panel
   - Verify no fault codes preventing restart
   - Initiate normal start sequence
2. If restart succeeds within 10 minutes: return to normal
3. If restart fails: continue on single chiller, schedule vendor call
4. If hall temperature rises >25°C: escalate to Tier B

**Tier B response (both chillers degraded)**

1. **Notify customer IT operations:**
   - Automated message via a3semi EPMS integration
   - Request workload reduction (15% target)
2. **Reduce facility cooling demand:**
   - CRAH fan speed max (uses more power but pushes air)
   - Ensure cold aisle containment fully closed
   - Verify hot aisle doors closed
3. **Workload migration:**
   - IT team migrates to secondary data center (Montreal)
   - Priority: training workloads first (most compute-heavy)
   - Next: inference workloads
   - Last: critical infrastructure (must run)

**Tier C response (total cooling loss)**

1. **Immediate 50% workload shed:**
   - IT automation reduces compute instantly
   - Non-critical jobs terminated
2. **Pre-EPO preparation:**
   - Facility engineer arrives at MEP room
   - Prepares for EPO activation if temperature continues rising
3. **Maximum airflow:**
   - All CRAHs at 100% speed
   - Emergency exhaust fans on (vents hot air outside)
4. **Contact utility and vendors:**
   - Johnson Controls emergency support
   - Utility emergency repair if upstream issue

### t+5min to t+15min: STABILIZE

**Target state:**
- Hall temperature stable or falling
- Load reduction sustained
- Root cause identified
- Recovery plan in execution

**Continuous monitoring:**
- Temperature trend graphs on main NOC screen
- Chiller status on SCADA dashboard
- Workload state via IT integration
- DLC flow per rack

### t+15min to Resolution: RECOVER

**Recovery actions:**

1. Complete repair of failed equipment
2. Restore full cooling capacity
3. Gradually return IT workloads (reverse migration)
4. Monitor closely for 1-hour post-recovery
5. Debrief and document

## Automated actions (EPMS executes)

When EOP-003 activates, EPMS automatically:

1. Records incident with severity=critical and source=COOLING
2. Queries RAG for matching Schneider WP122 mitigation content
3. Generates advisory text via Gemma 4 or Claude Sonnet
4. Displays advisory banner on dashboard (red)
5. Adjusts PUE alert thresholds (expect elevated PUE during event)
6. Enables heightened logging (5-second telemetry vs 15-second)
7. Correlates Morpheus data in case cyber involvement

## Coordination with IT operations

a3semi's IT team operates independently but coordinates during EOP-003:

### Communication channel

- Automated Slack/Teams channel: "A3-Alpha EOP-003"
- Includes: NOC operator, facility engineer, IT operations lead
- Updates every 5 minutes during active response

### Workload coordination

IT operations controls actual compute reduction. a3semi NOC provides:
- Temperature trend data
- Cooling capacity forecast
- Priority of facility recovery vs IT recovery
- Final decision authority on EPO activation

### Escalation path

If IT refuses workload reduction during Tier C:
1. NOC escalates to facility manager
2. Manager contacts IT operations VP
3. If unresolved: EPO authority with manager sign-off
4. Post-incident review mandatory

## EPO decision criteria

EPO activation is an EXTREME measure. Criteria:

EPO considered if ALL of:
- Tier C classification (total cooling loss)
- Temperature >33°C in any hall
- Temperature trend positive (rising)
- Time to A2 critical <2 minutes
- IT workload reduction ineffective
- Facility engineer confirms no alternative

EPO NOT activated if:
- Tier A or B (even if temperature elevated)
- Temperature stable, even if high
- Workload reduction in progress

Activating EPO when not warranted:
- Causes unnecessary service outage (customer SLA penalty)
- Damages equipment (especially GPUs mid-training)
- Triggers full investigation

## Post-incident activities

### Immediate (0-1 hour after recovery)

- Update incident status in PostgreSQL (status=RESOLVED)
- Send incident summary to facility manager
- Customer notification if impact exceeded SLA threshold
- NOC shift report entry with full timeline

### Short-term (1-24 hours)

- Root cause analysis (5-Why methodology)
- Corrective action plan development
- Vendor escalation if equipment issue
- Update EPMS thresholds if EOP triggered unnecessarily

### Long-term (1-7 days)

- P1 post-incident review (ISO 22301 requirement, 48-hour deadline)
- Procedure updates if gaps identified
- Training topic for next operator meeting
- Dashboard updates if visibility gaps found

## Common scenarios

### Scenario A: Chiller trip during peak summer

Trigger: Chiller 1 overpressure trip on 35°C day

Response:
1. Chiller 2 ramps to 100% (automatic)
2. Verify no rise in hall temperature (likely stable)
3. Diagnose Chiller 1: condenser fouling suspected
4. Schedule chemical cleaning within 7 days
5. Adjust PM schedule for next cycle

Duration: 15 minutes response, 1 hour stabilization

### Scenario B: DLC pump failure on CDU

Trigger: Secondary loop pump failure on Hall A CDU

Response:
1. Hall A DLC flow drops to ~25 L/min per rack
2. EPMS alerts IT to reduce Hall A workload 50%
3. Secondary pump auto-switches (2N design)
4. If switchover succeeds: minimal impact
5. If both pumps fail: escalate, migrate Hall A workload

Duration: 5-30 minutes depending on switchover success

### Scenario C: Total power loss

Trigger: Utility outage + generator failure

Response:
1. UPS provides 15 minutes (batteries)
2. IT operations initiates controlled shutdown
3. Cooling on UPS for 15 minutes (limited CRAH only)
4. Temperature rises, approaches A2 critical
5. Potential EPO if cooling unrecoverable

Duration: Critical, RTO 15 minutes per ISO 22301 P1

## References

- Schneider WP122 (T2-VEN-SE-WP122)
- Thermal model (T3-STD-THERMAL-MODEL)
- ISO 22301 (T3-STD-ISO-22301)
- EPO procedure (T1-SAF-EPO-005)
- a3semi EOP-003 Activation Log: A3-OPS-FRM-041
- a3semi BCDR Plan: A3-BUS-PLN-001
