# MCP tool catalog

All IDs are strings. Numeric Telegram chat and message IDs must also be passed as strings to
avoid precision loss in clients. Read tools use cursor-based pagination where applicable.

## Discovery and status

| Tool | Purpose |
| --- | --- |
| `get_status` | Count configured and ready accounts and bots. |
| `list_accounts` | Return stable account IDs, labels, Telegram identities, and states. |
| `list_bots` | Return stable bot IDs, labels, Telegram identities, and states. |
| `get_capabilities` | Describe limits, features, and identities visible to the current token. |

## Chats, folders, and messages

| Tool | Purpose |
| --- | --- |
| `list_chats` | List chats for an account. |
| `find_chats` | Find chats by name/title among the 500 most recent dialogs. |
| `resolve_peer` | Resolve an ID, username, Telegram link, or name to chat candidates. |
| `get_chat_info` | Return the type and core metadata of a chat. |
| `get_unread_inbox` | Return unread dialogs, mentions, reactions, and the latest message. |
| `get_inbox_context` | Return prioritized incoming context with several messages per chat. |
| `list_folders` | List Telegram folders with stable folder IDs and names. |
| `get_folder_messages` | Merge and search messages across the chats in one folder. |
| `get_chat_history` | Read chat history with optional inclusive date boundaries. |
| `search_messages` | Search within one chat. |
| `search_all_messages` | Search dialogs with date, sender, and attachment filters. |
| `get_message` | Fetch one message by ID. |
| `get_message_context` | Fetch a message and nearby messages. |
| `get_reply_thread` | Fetch the parent chain and direct replies. |
| `get_conversation_snapshot` | Return chat metadata, recent messages, and the pinned message. |
| `search_chat_content` | Find links, polls, GIFs, round videos, voice notes, or pinned messages. |
| `poll_updates` | Read new/edited/deleted messages, read markers, and reactions after a cursor. |
| `resolve_message_link` | Resolve public and private `t.me`/`telegram.me` message links. |
| `list_topics` | List forum topics in a supergroup. |
| `get_recent_mentions` | List recent mentions globally or within a chat. |

## Attachments

| Tool | Purpose |
| --- | --- |
| `list_attachments` | Find photos, videos, voice notes, audio, and documents in a chat. |
| `download_attachment` | Return images or files up to 10 MB in one MCP response. |
| `download_attachment_chunk` | Read a larger Telegram file in chunks of up to 4 MB. |
| `send_attachment` | Re-send an existing Telegram attachment without local file access. |
| `forward_messages` | Forward up to 100 messages between chats. |

Telegram currently accepts files up to 4 GB. This server does not impose a total file-size limit
when chunked download is used and does not create temporary files.

## Sending and chat state

| Tool | Purpose |
| --- | --- |
| `send_as_user` | Send plain text from an explicit account. |
| `send_as_bot` | Send plain text from an explicit bot. |
| `edit_own_message` | Edit a text message sent by the selected account. |
| `schedule_message` | Schedule a message from 10 seconds to 365 days ahead. |
| `list_scheduled_messages` | List scheduled messages in a chat. |
| `cancel_scheduled_message` | Cancel a scheduled message. |
| `mark_chat_read` | Mark a chat read through a specific message. |
| `react_to_message` | Set or remove a standard emoji reaction. |

Sending tools accept optional idempotency keys. Repeating a confirmed request with the same key
returns its stored result; using that key with different arguments returns an
`idempotency_conflict` error. Plain text is limited to 4,096 UTF-16 units, link previews are
disabled, and Markdown/HTML is not interpreted.

## Drafts and agent tokens

| Tool | Purpose |
| --- | --- |
| `create_draft` | Store a local message draft. |
| `list_drafts` | List drafts visible to the current token. |
| `send_draft` | Send a draft once and retain its delivery receipt. |
| `delete_draft` | Delete a local draft. |
| `create_agent_token` | Issue a scoped agent token (`admin` required). |
| `list_agent_tokens` | List token metadata (`admin` required). |
| `revoke_agent_token` | Revoke an agent token (`admin` required). |

Draft text is stored in the private state directory. A successfully sent draft is not sent again
when `send_draft` is retried.

## Limits and date handling

- `limit` is between 1 and 100. Continue with the returned `next_cursor`.
- `date_from` and `date_to` use `YYYY-MM-DD` and are inclusive.
- Folder queries accept an IANA `timezone_name` for local-day boundaries.
- Global queries inspect at most 10,000 results.
- A folder query merges up to 100 chats and 500 messages per page.
- `get_message_context` accepts up to 50 neighboring messages on each side.
- Cursors are signed and bound to their account, chat, query, and date range.
