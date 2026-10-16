# PollákCord Python bot client

Run this program on your own computer or VPS. PollákCord never runs your Python code. Python 3.11 or later is required.

From the source archive root:

```sh
python -m venv bot-env
. bot-env/bin/activate
pip install ./packages/pollakcord
export POLLAKCORD_ORIGIN=https://your-pollakcord.example
read -rsp 'Bot token: ' POLLAKCORD_BOT_TOKEN
export POLLAKCORD_BOT_TOKEN
python packages/pollakcord/examples/ping.py
```

Create a bot under Settings → Developer → Bots using your owner password. Copy its token once. Ask a server owner or Administrator to paste its install code into Server settings → Integrations · Bots, review the permission checklist and confirm. Keep the example running, open an installed server text channel and select `/ping`. Sending `!ping` also works when the bot has view, history and send permissions.

Tokens belong in environment variables or a secret manager. Never commit, print or share them. Revealing a replacement token and regenerating a token both invalidate the old token and disconnect its gateway. Update the environment and restart the bot. The client deliberately stops on disconnect; restart with backoff in your own process manager. One gateway is allowed per bot, three per owner.

`Bot.on_message` receives authorized server text messages from humans, omitting bot authors to prevent loops. `Bot.slash(name, description, options=..., default_member_permissions=...)` registers slash handlers. Option types are `string`, `int`, `bool`, `channel` and `user`; each option has a name, description, type and optional required boolean. `Interaction.options` contains the supplied values. Call `await interaction.respond(text)` once within three seconds. Responses are public channel messages. Offline and timeout errors are shown to the invoker. There is no deferred or ephemeral reply mode.

Available async methods: `current()`, `servers()`, `channels(server_id)`, `send_message(channel_id, content)`, `delete_message(channel_id, message_id)`, `list_commands()`, `register_commands(definitions)` and `respond(interaction_id, content)`. The SDK uses `/api/v1/bots/api/` and `/api/v1/bots/gateway` with `Authorization: Bot <token>`. It does not follow redirects or use browser cookies. Use HTTPS outside local development.

Registration replaces the bot's command definitions and preserves IDs for names that still exist. At most 25 commands and 10 options per command are allowed. Registration is limited to 3 calls per minute per bot and 6 per owner. Sends, including slash responses, are limited to 8 per 10 seconds per bot and 16 per owner. Handle `BotHTTPError.status` and `.code` in your program; HTTP errors do not include the token.

Bot attachments are deferred to a follow-up. Message sending is text-only; owner-uploaded avatar and banner images reuse the normal profile image processing. No voice, DMs, DÖK, class spaces, form results, identity reveal or platform staff APIs are available to bots. Publishing this package to PyPI is a separate manual step.
