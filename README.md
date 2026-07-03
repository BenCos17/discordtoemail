# Discord to Email Forwarder

This script watches one Discord channel and forwards each new message to one or more email addresses using SMTP.
Messages that arrive within a five-minute quiet window are grouped into a single email.

## Files

- `discord_email_forwarder.py`: the bot script
- `requirements.txt`: Python dependencies
- `.env.example`: configuration template

## Setup

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env` and fill in your values.

3. In the Discord Developer Portal, enable the `Message Content Intent` for your bot.

4. Run the script:

```bash
python discord_email_forwarder.py
```

## Notes

- `SOURCE_CHANNEL_ID` should be the numeric ID of the Discord channel you want to watch.
- `EMAIL_TO` accepts one or more comma-separated recipient addresses.
- `GROUP_WINDOW_SECONDS` controls how long the script waits after the last message before sending a grouped email. The default is 300 seconds.
- If your email provider requires it, use an app password rather than your normal password.
- The script forwards plain text, author info, a jump link, and attachment URLs.
