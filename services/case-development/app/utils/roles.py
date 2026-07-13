"""
Role name normalisation utility.

The Firestore ``staff`` collection was seeded with a mix of display-format role
values ("Paralegal", "Senior Partner", …) and code-format values ("paralegal",
"senior_partner", …).  All internal RBAC logic uses code-format only.  This
module provides a single conversion point so every service reads through
``normalize_role()`` before comparing or storing a role string.
"""

# Map from display name → internal code name.
# Values that are already in code format pass through unchanged (see below).
ROLE_DISPLAY_TO_CODE: dict[str, str] = {
    "Paralegal":      "paralegal",
    "Junior Partner": "junior_partner",
    "Senior Partner": "senior_partner",
    "System Admin":   "system_admin",
    "Admin Staff":    "admin_staff",
}


def normalize_role(role: str) -> str:
    """Convert a display-format role string to its internal code-format equivalent.

    If the value is already in code format (e.g. ``"paralegal"``) it is returned
    unchanged, so this function is safe to call unconditionally on any role string
    regardless of its origin.

    Examples::

        normalize_role("Paralegal")      # → "paralegal"
        normalize_role("Senior Partner") # → "senior_partner"
        normalize_role("admin_staff")    # → "admin_staff"  (pass-through)
        normalize_role("")               # → ""
    """
    return ROLE_DISPLAY_TO_CODE.get(role, role)
