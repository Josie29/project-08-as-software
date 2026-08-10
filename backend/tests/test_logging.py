from app.logging import redact_phi


def test_redact_phi_scrubs_patient_identifying_values() -> None:
    """A PHI value reaching application logs is a HIPAA incident, not a cosmetic bug;
    this processor is the last line of defence if a call site passes one by mistake."""
    event = {
        "event": "identity.verify_failed",
        "dob": "1988-03-14",
        "email": "patient@example.com",
        "patient_uuid": "8f14e45f-ceea-467a-9f39-1b2c3d4e5f60",
    }

    scrubbed = redact_phi(None, "info", event)

    assert scrubbed["dob"] == "[redacted]"
    assert scrubbed["email"] == "[redacted]"
    # Opaque identifiers are the intended way to make a log line debuggable.
    assert scrubbed["patient_uuid"] == "8f14e45f-ceea-467a-9f39-1b2c3d4e5f60"


def test_redact_phi_is_case_insensitive() -> None:
    """Key casing varies across call sites; a case-sensitive check would leak PHI
    from any caller that used a different convention."""
    scrubbed = redact_phi(None, "info", {"DOB": "1988-03-14", "Authorization": "Bearer x"})

    assert scrubbed["DOB"] == "[redacted]"
    assert scrubbed["Authorization"] == "[redacted]"
