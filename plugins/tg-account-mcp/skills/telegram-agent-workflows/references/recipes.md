# TG Account MCP recipes

## Read a named dialog over a date range

1. `list_accounts` and select the explicit `account_id`.
2. `find_chats(account_id, query)`; fall back to `resolve_peer` for a username, link, or ID.
3. Resolve ambiguity before continuing.
4. `get_chat_history` with `date_from`, `date_to`, and the resolved `chat_id`.
5. Continue with `next_cursor` until exhausted or the user's requested bound is met.

## Review today's folder messages for personal tasks

1. `list_accounts`, then `list_folders(account_id)`.
2. Match the folder by its returned name and retain its stable ID.
3. `get_folder_messages` with equal local `date_from` and `date_to` values plus
   `timezone_name`.
4. Continue cursor pages and group relevant results by task, deadline, and originating chat.
5. Keep uncertain assignments separate from tasks that explicitly name the user.

## Find and download an attachment

1. Resolve the account and chat.
2. `list_attachments` with the narrowest useful media and date filters.
3. Choose the message by metadata rather than filename alone.
4. Use `download_attachment` when the response fits its 10 MB limit.
5. Otherwise call `download_attachment_chunk`, preserving the returned offset until complete.

## Prepare or send a reply

1. Resolve the identity and chat; use `get_message_context` when replying to a specific message.
2. If the user asked for a draft, call `create_draft` or return the proposed text.
3. If the user asked to send, call the matching user or bot send tool with an idempotency key.
4. Return the delivery receipt. On timeout, retry only with the identical arguments and key.


## Read or enable a local archive

1. Check `get_capabilities`: archive tools require a server advertising `local_archive`.
2. Resolve the account and chat. Use `get_archive_status` to inspect existing observed coverage.
3. If the user explicitly requests archiving, use an admin token with `configure_chat_archive`.
   Retain deleted text only when the user specifically authorizes that setting; default to false.
4. Use `sync_chat_archive` for one bounded history page, or let the background worker continue.
5. Retrieve with `search_archive`; follow cursors up to the requested bound. Cite the returned
   account/chat/message IDs and message dates. Do not describe lexical search as semantic search.
6. Inspect `get_message_versions` to distinguish observed edits from the current saved text.
7. For export use `export_chat_archive` and continue until `next_cursor` is absent. File bytes
   and historical versions are not part of this export.
8. Disable capture to pause; use `purge_chat_archive` only when the user requests local deletion.
   Never interpret deletion of a Telegram message as authorization to retain its contents.
