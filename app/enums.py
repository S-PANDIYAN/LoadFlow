"""Shared enums for account types, org types, load states."""
import enum


class OrgType(str, enum.Enum):
    BROKER = "BROKER"
    CARRIER = "CARRIER"


class AccountType(str, enum.Enum):
    BROKER = "BROKER"
    CARRIER = "CARRIER"
    SHIPPER = "SHIPPER"


class LoadState(str, enum.Enum):
    POSTED = "POSTED"
    CARRIER_ASSIGNED = "CARRIER_ASSIGNED"
    RATE_CONFIRMED = "RATE_CONFIRMED"
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    POD_VERIFIED = "POD_VERIFIED"
    CLOSED = "CLOSED"  # Invoiced/Closed


# Legal forward transitions of the load lifecycle state machine.
# Server-side enforcement: any transition not listed here is rejected.
LOAD_TRANSITIONS: dict[LoadState, list[LoadState]] = {
    LoadState.POSTED: [LoadState.CARRIER_ASSIGNED],
    LoadState.CARRIER_ASSIGNED: [LoadState.RATE_CONFIRMED, LoadState.POSTED],  # back to POSTED on decline/unassign
    LoadState.RATE_CONFIRMED: [LoadState.DISPATCHED],
    LoadState.DISPATCHED: [LoadState.IN_TRANSIT],
    LoadState.IN_TRANSIT: [LoadState.DELIVERED],
    LoadState.DELIVERED: [LoadState.POD_VERIFIED],
    LoadState.POD_VERIFIED: [LoadState.CLOSED],
    LoadState.CLOSED: [],
}

# States beyond CARRIER_ASSIGNED are blocked while a load is compliance-flagged.
STATES_REQUIRING_COMPLIANCE = {
    LoadState.RATE_CONFIRMED,
    LoadState.DISPATCHED,
    LoadState.IN_TRANSIT,
    LoadState.DELIVERED,
    LoadState.POD_VERIFIED,
    LoadState.CLOSED,
}


class AuthorityStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    SUSPENDED = "SUSPENDED"
