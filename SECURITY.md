# Security Policy

## Scope
The current release is for local research and paper trading. It does not implement live exchange orders or store exchange credentials.

## Reporting a vulnerability
Please do not publish exploitable details in a public issue. Contact the repository owner privately through GitHub profile contact options, if available. Include a minimal reproduction, affected version/commit, and impact. Never include real secrets or account data.

## Safety
- Keep the read-only API bound to localhost.
- Do not put secrets in issues, logs, commits, screenshots, or test fixtures.
- Treat market data as untrusted input.
- Any future credential or live execution feature requires separate threat modeling and security review.
