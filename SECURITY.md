# Security

## Deployment warning

The dashboard and API have **no built-in login**. By default they bind to `127.0.0.1` only. Never expose
them to the internet as they are. Either turn on nginx basic auth (`deploy/nginx/auth.example.conf`) or
put them behind a VPN or an access proxy.

Keep API keys in `deploy/.env` (git-ignored). Never commit them.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's
[private vulnerability reporting](https://github.com/vdat-18/ai-content-automation/security/advisories/new)
for this repository. Include the steps to reproduce and the version or commit.

This is a personal project, so there is no guaranteed response time, but reports are read and taken
seriously.
