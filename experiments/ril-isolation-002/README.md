# RIL-ISOLATION-002 — fast preflight-qualified Temporary Chat check

RIL-ISOLATION-001 failed because ordinary New Chat windows were used instead of Temporary Chat.

This successor adds a hard precontact gate: **no canary is generated until the operator confirms the Temporary Chat indicator is visible and 3.8 Flash is selected.**

Primary is deliberately small: two independent paired trials. Each trial uses one Temporary Chat for exposure + same-chat recall and one fresh Temporary Chat for a blind cross-chat probe. After both trials, Recent and Gemini Apps Activity are checked once.

Pass means only that two paired trials showed no observable exact-canary inheritance under the frozen Gemini Temporary Chat procedure. It does not prove provider-internal deletion, absence of hidden state, hostile isolation, or anomaly-first advantage.

If it passes, the next experiment may be `RIL-ANOMALY-002` using this exact substrate with arm-local receiver-held ratchets.
