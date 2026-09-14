# RIL-RELAY-001 operator card

1. In the Linux VM, open Chrome normally, sign into Google yourself, select the same qualified Gemini Flash Extended state, and expose Chrome on localhost CDP (for example `--remote-debugging-port=9222`). Do not give the relay a password, recovery code, 2FA secret, exported cookies, or Google token.
2. Install the transport dependency only: `python -m pip install playwright`. No Playwright browser download is needed when attaching to an existing Chrome CDP session.
3. Run `python experiments/ril-relay-001/verify_repo.py` then `python experiments/ril-relay-001/protected/relay_driver.py self-check`.
4. Run `python experiments/ril-relay-001/protected/relay_driver.py qualify --output /tmp/ril-relay-001`.
5. Do not retry a failed qualification contact. A UI mismatch, login page, timeout, unexpected blind recall, or parse failure is the result. Preserve `/tmp/ril-relay-001`.

The relay is transport only. It is not allowed to reason about experiment content, rewrite packets, repair a response, or carry chat text between fresh Temporary Chats.
