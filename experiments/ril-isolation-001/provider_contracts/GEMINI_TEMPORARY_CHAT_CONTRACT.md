# Gemini Temporary Chat contract — frozen for RIL-ISOLATION-001

Observed/documented boundary used by this experiment:

- Product surface: Gemini mobile app / Gemini web app, consumer account.
- Research model: **3.8 Flash**, selected visibly in the consumer UI before each trial.
- Every exposure and blind probe must start in **Temporary Chat**.
- Google documents that Temporary Chats do not appear in recent chats or Gemini Apps Activity, do not provide personalized responses, and do not save information for future personalization.
- Google also documents that Temporary Chats can be retained with the account for up to 72 hours for service/safety purposes. This experiment therefore does **not** claim provider-internal deletion or absence of provider-side retention.
- Connected Apps and other integrations requiring Keep Activity are unavailable in Temporary Chat.

Primary references observed before preregistration:

- https://support.google.com/gemini/answer/13275745
- https://support.google.com/gemini/answer/13594961
- https://support.google.com/gemini/answer/16598469

The receiver tests the user-visible inheritance boundary, not Google's internal storage architecture.
