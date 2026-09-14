# RIL-RELAY-002

Successor to the terminal `RIL-RELAY-001` egress failure.

The only design change is to separate unauthenticated Gemini network-path preflight from the authenticated primary qualification. Muse may test candidate execution hosts without user credentials. The first authenticated primary run must be bound to a host that already produced a PASS preflight receipt.

Predecessor freeze SHA256: `d2bc80967450e12da848577b5eb4e1fce1085bd7b8673aaf7d7f847331bfd0de`.

A PASS authorizes `RIL-ANOMALY-003` on the exact selected host and relay contract. It does not establish portability across hosts or provider-internal isolation.
