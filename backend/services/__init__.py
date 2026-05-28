"""DC-EPMS PRO -- in-process services that wrap stateful subsystems
(QKD pool, future PTP probe, etc.). Each module here owns a small
piece of process-lifetime state and is started/stopped from the
FastAPI lifespan in `backend.main`.
"""
