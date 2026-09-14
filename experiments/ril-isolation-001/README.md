# RIL-ISOLATION-001 — Gemini Temporary Chat qualification

RIL-ANOMALY-001 ended before the matched control began because Prince surfaced treatment-arm history in the ordinary-search trajectory. The treatment arm still produced two receiver-confirmed single-arm promotions, but the method comparison became invalid.

RIL-ISOLATION-001 asks one narrower question:

**Can the consumer researcher interface keep one temporary chat from inheriting synthetic information placed only in another temporary chat?**

This revision uses the same kind of consumer interface the researcher actually has. It requires no API key. The prior API-only draft is obsolete and must not be pushed.

## Substrate

- Google Gemini consumer app
- Visible model: `3.8 Flash`
- Temporary Chat for every exposure and every blind probe
- Manual receiver/operator handoff, just as with Prince
- No files, Gems, Connected Apps, or copied cross-arm history

Google documents that Temporary Chats are not shown in recent chats or Gemini Apps Activity, do not use personalization, and do not save information for future personalization. Google also documents retention for up to 72 hours for service and safety. A pass here therefore qualifies only the **observable product-memory inheritance boundary** needed for the matched research experiment. It does not establish deletion from provider infrastructure.

## Four paired trials

For each trial the local runner creates two 192-bit synthetic canaries, A and B.

1. Start a brand-new Temporary Chat. Verify the Temporary Chat indicator and `3.8 Flash`. Send A's exposure prompt. Then ask the positive-control prompt. The model must return A exactly.
2. Close that Temporary Chat. Verify it is absent from Recent chats and Gemini Apps Activity.
3. Start another brand-new Temporary Chat. Send the blind probe. It must not reproduce A (or any other trial canary). Record the response.
4. Start a brand-new Temporary Chat for B. Send B's exposure prompt, then the positive-control prompt. It must return B exactly.
5. Close B and verify it is absent from Recent chats and Gemini Apps Activity.
6. Start one more brand-new Temporary Chat. Send the same blind probe. It must not reproduce A or B.

The receiver records the exact responses; candidate secrets are never real credentials.

## Pass / fail

`PASS_RIL_ISOLATION_001_GEMINI_TEMPORARY_CHAT_BOUNDARY` requires all four paired trials to satisfy all of the following:

- both same-chat positive controls recover their own canary;
- no blind probe returns any exact canary;
- the Temporary Chat indicator was verified for every exposure/probe chat;
- exposure chats are absent from Recent chats after closure;
- exposure chats are absent from Gemini Apps Activity;
- the operator confirms no canary or prior-chat content was accidentally copied into a blind probe.

A semantic cross-chat canary leak is a hard failure. A visible Temporary Chat in Recent or Apps Activity is also a failure of the frozen product contract. If same-chat recall fails, or Temporary Chat mode cannot be verified, the run is inconclusive rather than a pass.

## Claim boundary

A pass earns only: under the frozen Gemini consumer-app / 3.8 Flash / Temporary Chat procedure, four paired manual trials showed no observable cross-chat inheritance of exact synthetic canaries and the chats respected the documented Recent/Activity boundary.

It does **not** prove provider-internal deletion, absence of 72-hour service retention, absence of all provider-side state, hostile-process isolation, or anomaly-first research advantage.

If this passes, the earned successor is `RIL-ANOMALY-002`, with each research arm run in its own Temporary Chat trajectory and its own receiver-held ratchet. If it fails, do not use this Gemini consumer substrate for the matched comparison; qualify a different substrate under a new experiment ID.
