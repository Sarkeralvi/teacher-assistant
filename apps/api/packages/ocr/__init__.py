"""Engine-agnostic tier-1 OCR types and escalation policy.

Deliberately free of I/O, models and database access so the escalation decision
is a pure function of recorded inputs and can be audited and unit-tested.
"""
