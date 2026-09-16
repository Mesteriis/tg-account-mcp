# Launch notes

## Positioning

Use one concrete sentence consistently:

> A self-hosted MCP server that gives consent-based AI workflows controlled access to multiple
> Telegram accounts and optional bots, with QR/2FA onboarding, folder-aware search, attachments,
> and scoped tokens.

Lead with the agent workflows rather than the dashboard. Useful demonstrations are:

1. “Find this synthetic contact by transliterated name and summarize our test messages.”
2. “Review today's messages in our consenting test workspace and identify tasks assigned to me.”
3. “Download the attachment from this message, draft a reply, and wait for approval before send.”
4. “Give a research agent read-only access to one account and one chat.”

Record demos with a dedicated test account or fully synthetic/redacted chat data. Never show QR
login URLs, Telegram sessions, API credentials, Bearer tokens, passwords, private chat names, or
message content without consent.

## Where to announce

Publish the canonical release on GitHub first, then PyPI, GHCR, and the official MCP Registry.
Use Smithery as a secondary MCP directory. For feedback and early users, post to:

- Hacker News as a **Show HN**;
- Reddit communities focused on MCP, local AI agents, and self-hosting;
- community-run MCP forums where project announcements are explicitly allowed;
- a short technical thread on X, LinkedIn, or a personal blog;
- relevant Telegram developer communities where self-promotion is allowed.

Do not post the same generic announcement everywhere. Match the example and technical depth to
the community and stay available to answer setup and security questions.

## Draft Show HN post

**Title**

> Show HN: A self-hosted MCP server for multiple Telegram accounts

**Body**

> I built an open-source MCP server for agents that need to work with Telegram without turning
> the UI into another Telegram client. It connects multiple user accounts through QR login and
> optional 2FA, supports bots separately, and requires every tool call to select the sender.
>
> The useful agent workflows are folder-wide and date-bounded search, transliterated chat lookup,
> unread/inbox context, attachment downloads, threads/topics, drafts, and controlled sending.
> Agent tokens can be read-only or send-enabled and restricted to specific identities and chats.
>
> It is self-hosted because Telegram sessions are sensitive. The repository includes a local
> setup UI, Docker Compose with HTTPS, 44 MCP tools, and tests that use fake Telegram adapters.
> I would especially value feedback on the tool boundaries and least-privilege model.
>
> This is an unofficial integration. Telegram's current API and content terms require the account
> owner's knowledge for actions and specific continuing consent from every relevant user before
> their content is provided to an AI system, so the README makes that operating boundary explicit.

Add the actual GitHub URL and one short demo after the repository is public.

## Draft short announcement

> Released TG multi-account MCP: an unofficial self-hosted server for consent-based agent
> workflows over Telegram chats and folders, with explicitly selected user or bot senders.
> QR/2FA onboarding, scoped agent tokens, Docker Compose, 44 tools, Apache-2.0. [repository link]

Replace `[repository link]` only after the public repository exists.
