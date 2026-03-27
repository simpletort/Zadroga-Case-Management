import os
import pytest

# Set required env vars before main.py is imported
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("SENDGRID_API_KEY", "SG.test")
os.environ.setdefault("FROM_EMAIL", "noreply@test.com")
os.environ.setdefault("ADMIN_EMAIL", "admin@test.com")


FORM_CONFIG = {
    "formBaseUrl": "https://docs.google.com/forms/d/TEST_FORM_ID/viewform",
    "fieldMappings": {
        "firstName":   "entry.111",
        "lastName":    "entry.222",
        "email":       "entry.333",
        "phone":       "entry.444",
        "intakeToken": "entry.555",
    },
}

CASE_DATA = {
    "status": "New Lead",
    "leadData": {
        "firstName": "John",
        "lastName":  "Smith",
        "email":     "john.smith@example.com",
        "phone":     "+12125550000",
    },
}


@pytest.fixture(autouse=True)
def reset_module_singletons():
    """Reset cached module-level singletons between tests."""
    import main
    main._db = None
    main._form_config = None
    yield
    main._db = None
    main._form_config = None
