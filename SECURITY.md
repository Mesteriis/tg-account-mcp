# Security policy

## Supported versions

This project is pre-1.0. Security fixes are applied to the latest released version only.

| Version | Supported |
| --- | --- |
| 0.4.x | Yes |
| Earlier releases | No |

## Reporting a vulnerability

Use the repository's **Security → Report a vulnerability** form to send a private GitHub Security
Advisory. Do not include vulnerability details, Telegram sessions, API credentials, MCP tokens,
bot tokens, passwords, or message content in a public issue.

If private vulnerability reporting is not enabled, open a public issue that asks the maintainer
for a private contact channel without describing the vulnerability.

Please include the affected version, deployment shape, impact, reproduction steps, and any
proposed mitigation. Redact all secrets and personal Telegram data. You should receive an initial
response within seven days; disclosure timing will be coordinated after impact and remediation
are understood.

## If a secret or session was exposed

1. Stop the service or remove public access.
2. Revoke affected sessions in **Telegram → Settings → Devices**.
3. Rotate bot tokens through BotFather when applicable.
4. Rotate the main MCP token and revoke affected agent tokens.
5. Replace exposed Telegram API credentials if they were included.
6. Review access logs without copying message content or credentials into an issue.
