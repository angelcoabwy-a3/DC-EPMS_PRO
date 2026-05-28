"""DC-EPMS PRO -- Epic 10 IAM (Identity & Access Management).

Stateless JWT-based authentication + role-rank gating. The in-memory
user store is a demo MVP: production deployments must wire a real
identity backend (LDAP/OIDC/SAML) via the same models.User shape.

Companion: backend.ledger.forensic_ledger (the audit trail records
the JWT-derived user_id on every signed action).
"""

from backend.auth.models import ROLE_RANK, Role, User, role_at_least

__all__ = ["ROLE_RANK", "Role", "User", "role_at_least"]
