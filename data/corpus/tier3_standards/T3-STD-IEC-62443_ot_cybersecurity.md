---
doc_id: T3-STD-IEC-62443
tier: 3
priority: medium
domain: ot_cybersecurity
standard: IEC 62443-3-3
applies_to: [ot_zones, network_isolation, soar, morpheus_integration]
keywords: [iec_62443, zones, sl_0, sl_1, sl_2, sl_3, segmentation, ot_security]
facility: A3-Alpha Toronto Area
---

# IEC 62443 — OT Cybersecurity Zones and Conduits

Source: IEC 62443-3-3 (Industrial communication networks — Network and
system security — System security requirements and security levels)

## Why IEC 62443 for a data center?

Data centers contain significant Operational Technology (OT) alongside
Information Technology (IT):

- Chillers, UPS, PDUs, switchgear — all have embedded controllers
- BMS (Building Management System) — coordinates HVAC and alarms
- Fire alarm, access control, video surveillance — life safety OT
- DLC flow controllers, leak detection, humidity control — cooling OT

A cyber attack on OT can cause physical harm (overheating, fire,
electrical fault). IEC 62443 provides the framework to protect OT.

## Security Levels (SL-0 through SL-4)

IEC 62443-3-3 defines 5 security levels based on the capability of the
adversary:

| Level | Adversary capability | A3-Alpha zones |
|-------|----------------------|----------------|
| SL-0 | No specific requirements (default IT) | Enterprise IT, internet zone |
| SL-1 | Casual/coincidental violation | EPMS/SCADA operator zone |
| SL-2 | Intentional, simple means, low resources | Chiller/UPS OT control |
| SL-3 | Intentional, sophisticated, moderate resources | Life safety (fire, EPO) |
| SL-4 | Intentional, sophisticated, extensive resources | Nuclear/critical national infrastructure (not applicable) |

## A3-Alpha zone architecture

### SL-0: Enterprise IT zone
- Office network, developer workstations, email, internet browsing
- Corporate firewalls at internet boundary
- NO direct access to any OT system

### SL-1: EPMS/SCADA zone  
- DC-EPMS PRO dashboard (this system)
- Operator terminals with limited OT visibility
- Read-only access to aggregated telemetry
- Signed/authenticated user access

### SL-2: OT control zone
- Chiller controllers, UPS BMS ports, PDU monitoring
- NVIDIA Morpheus Sentinel monitoring Modbus TCP / DNP3 traffic
- SOAR (Security Orchestration, Automation, Response) can isolate this
  zone on anomaly detection
- Isolation preserves physical safety functions

### SL-3: Life safety zone
- Fire alarm panel, gas suppression systems
- Emergency Power Off (EPO) circuits
- Access control, intrusion detection
- Hardened communication (fiber only, no Ethernet bridges)
- No remote access; local operator interface only

## Conduits — connections between zones

A conduit is a communication pathway between zones. IEC 62443 requires
each conduit to be classified and controlled:

| Conduit | From | To | Protection |
|---------|------|----|-----------:|
| C-IT-EPMS | SL-0 | SL-1 | Firewall, authenticated access, application gateway |
| C-EPMS-OT | SL-1 | SL-2 | Protocol gateway (Modbus/DNP3 translation), deep inspection |
| C-SL2-SL3 | SL-2 | SL-3 | Physically isolated (fiber only), no IP routing |

## SR (System Requirements) — the 7 foundational requirements

IEC 62443-3-3 defines 7 System Requirements. A3-Alpha implements all 7:

### SR 1: Identification and authentication control

- Every device and user has unique identity
- No shared passwords
- RADIUS authentication for network access
- Certificates for device-to-device authentication

### SR 2: Use control

- Role-based access control (RBAC)
- NOC operator: read-only for most, control for assigned zones
- Facility engineer: full control within their zone
- Administrator: separate credentials, 2FA required

### SR 3: System integrity

- Code signing on all firmware/software
- Secure boot on control systems
- NIDS (network intrusion detection) via Morpheus
- Regular vulnerability scanning (non-intrusive to OT)

### SR 4: Data confidentiality

- Encrypted communications where technically feasible
- Modbus TCP encapsulated in TLS where supported
- DNP3 Secure Authentication mandatory for any remote access

### SR 5: Restricted data flow (ZONE ISOLATION)

This is the key requirement for A3-Alpha. SR 5.2 specifies:

> "The control system shall provide the capability to deny general
> purpose communications not explicitly required for the zone's
> operation."

Implementation:
- Firewalls at each zone boundary, default-deny policy
- Allowlist of expected protocols/ports per zone
- Anomaly detection via Morpheus triggers SOAR isolation
- Confidence threshold: 85% triggers automatic zone isolation

### SR 6: Timely response to events

- Continuous monitoring via Morpheus AI Sentinel
- Incidents logged to PostgreSQL with severity and source=MORPHEUS
- Alert to NOC within 5 seconds of anomaly detection
- Post-incident review within 24 hours per ISO 22301

### SR 7: Resource availability

- Redundant control paths (A and B networks)
- Failover tested quarterly
- Availability target 99.99% per Tier IV

## NVIDIA Morpheus integration — the details

Morpheus AI Sentinel is an NVIDIA AI framework for cybersecurity,
optimized for:

- Streaming inspection of Modbus TCP, DNP3, OPC UA protocols
- Pattern detection using deep learning (GPU-accelerated)
- Baseline learning for each zone
- Anomaly correlation across protocols

### Baseline behavior at A3-Alpha

Normal Modbus traffic:
- 2,847 messages/second (measured baseline)
- Read holding registers dominant (polling telemetry)
- Write coils infrequent (operator commands)
- Source IPs: known SCADA terminals only
- Destination IPs: known OT devices

Normal DNP3 traffic:
- 150 messages/second (slower protocol, less telemetry)
- Class 1/2/3 polls from RTU
- Unsolicited reports on critical events

### Anomaly triggers

Morpheus detects and classifies anomalies:

- Unexpected source IP → potential lateral movement
- Unknown function code → reconnaissance or exploit attempt
- Traffic burst → DoS attempt or misconfigured device
- Pattern mismatch to baseline → suspicious behavior
- Cross-protocol correlation (e.g., Modbus + physical alarm) → cyber-
  physical attack

### Confidence-based response

- Confidence <50%: log only, no action
- 50-85%: alert NOC, operator decides
- >85%: automatic SOAR isolation of affected device (SR 5.2)
- Isolation preserves physical function (chiller keeps running on local
  control, just isolated from the network)

## Physical vs cyber separation

SL-2 and SL-3 must remain functional even if the IT network is
compromised. This requires:

- Local control loops on chillers (won't shut down if network lost)
- Hardwired safety interlocks (fire alarm, EPO) that don't traverse IP
  networks
- Mechanical fail-safes (chilled water thermal mass = 5 minutes of
  inertia)

A3-Alpha tests these separations quarterly via blackout drills —
simulate total IT network loss and verify physical systems continue
operating.

## Compliance and audit

A3-Alpha follows IEC 62443-2-4 requirements for service providers:

- Annual security audit by third party
- Penetration testing of SL-0 and SL-1 boundaries (with permission)
- Vulnerability management per CVE announcements
- Security incident reporting to customers within SLA

## Training

- All NOC personnel: IEC 62443 awareness (8 hours initial, 4 hours annual)
- OT engineers: IEC 62443-2-4 certified (formal course)
- Facility manager: IEC 62443-3-3 advanced training
- Morpheus administrators: NVIDIA Morpheus training + annual refresher

## Common incidents and response

### Scenario: Unknown device on OT network

Morpheus detects: traffic to/from unrecognized MAC address

1. SOAR isolates the device's port on the managed switch
2. Alert to NOC with severity=warning
3. Physical investigation: dispatch to device location
4. Legitimate device (new chiller controller added): approve,
   update allowlist
5. Unauthorized device: remove, report as security incident

### Scenario: Modbus traffic burst from chiller controller

Morpheus detects: traffic 10x baseline from known source

1. Verify physical chiller state (EPMS check)
2. If chiller behaving normally: likely firmware glitch, schedule
   controller reboot during next maintenance window
3. If chiller behaving abnormally: potential cyber incident,
   isolate and investigate

### Scenario: DNP3 unsolicited message storm

Morpheus detects: rapid Class 1 unsolicited messages

1. Classify by source: if legitimate alarm cascade (fire, flooding),
   this is correct — do not suppress
2. If no physical correlate: potential DoS attack or RTU malfunction
3. Alert NOC, investigate physical conditions first

## References

- IEC 62443-3-3 (System security requirements)
- IEC 62443-2-4 (Security program requirements for service providers)
- NIST SP 800-82 Rev 3 (Guide to ICS Security)
- NVIDIA Morpheus documentation
- a3semi Cybersecurity Policy: A3-SEC-POL-001
- a3semi Annual Security Audit: archived in `procedures`
