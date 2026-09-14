# Operator card — 5 minutes

## Before any canary
Open Gemini → Temporary Chat → 3.8 Flash.
Confirm the Temporary Chat indicator is visible.
Do not send an experiment prompt until the receiver records that preflight.

## Then two trials
Each trial:
1. Temporary Chat: exposure prompt → expect ACK.
2. Same chat: recall prompt → exact canary.
3. Close it.
4. Fresh Temporary Chat: blind probe → record exact response.
5. Close it.

After both trials, check once:
- neither exposure chat appears in Recent;
- neither exposure chat appears in Gemini Apps Activity.

Total: 4 Temporary Chats, 6 prompts, 2 final UI checks.
