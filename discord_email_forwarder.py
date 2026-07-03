import asyncio
import os
import smtplib
import mimetypes
from email.message import EmailMessage

import discord
from dotenv import load_dotenv


load_dotenv()

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
SOURCE_CHANNEL_ID = int(os.getenv("SOURCE_CHANNEL_ID", "0"))
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USERNAME)
EMAIL_TO = [address.strip() for address in os.getenv("EMAIL_TO", "").split(",") if address.strip()]
EMAIL_SUBJECT_PREFIX = os.getenv("EMAIL_SUBJECT_PREFIX", "Discord alert")
USE_SSL = os.getenv("SMTP_USE_SSL", "true").lower() in {"1", "true", "yes", "on"}


if not DISCORD_BOT_TOKEN:
    raise SystemExit("Missing DISCORD_BOT_TOKEN")
if not SOURCE_CHANNEL_ID:
    raise SystemExit("Missing SOURCE_CHANNEL_ID")
if not SMTP_HOST:
    raise SystemExit("Missing SMTP_HOST")
if not SMTP_USERNAME:
    raise SystemExit("Missing SMTP_USERNAME")
if not SMTP_PASSWORD:
    raise SystemExit("Missing SMTP_PASSWORD")
if not EMAIL_TO:
    raise SystemExit("Missing EMAIL_TO")
if not EMAIL_FROM:
    raise SystemExit("Missing EMAIL_FROM")


intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


async def build_email(message: discord.Message) -> EmailMessage:
    email = EmailMessage()
    author_name = f"{message.author.display_name} ({message.author})"
    subject = f"{EMAIL_SUBJECT_PREFIX}: #{message.channel.name} - {message.author.display_name}"
    timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    attachments = "\n".join(f"- {attachment.filename}: {attachment.url}" for attachment in message.attachments)
    if not attachments:
        attachments = "None"

    body = (
        f"Channel: #{message.channel.name}\n"
        f"Server: {message.guild.name if message.guild else 'Direct Message'}\n"
        f"Author: {author_name}\n"
        f"Time: {timestamp}\n"
        f"Message ID: {message.id}\n"
        f"Link: {message.jump_url}\n\n"
        f"Content:\n{message.content or '[no text content]'}\n\n"
        f"Attachments:\n{attachments}\n"
    )

    email["From"] = EMAIL_FROM
    email["To"] = ", ".join(EMAIL_TO)
    email["Subject"] = subject
    email.set_content(body)

    for attachment in message.attachments:
        file_bytes = await attachment.read()
        content_type = attachment.content_type or mimetypes.guess_type(attachment.filename)[0] or "application/octet-stream"
        maintype, subtype = content_type.split("/", 1)
        email.add_attachment(
            file_bytes,
            maintype=maintype,
            subtype=subtype,
            filename=attachment.filename,
        )

    return email


def send_email(email: EmailMessage) -> None:
    if USE_SSL:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(email)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(email)


@client.event
async def on_ready() -> None:
    print(f"Logged in as {client.user} and watching channel {SOURCE_CHANNEL_ID}")


@client.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return
    if message.channel.id != SOURCE_CHANNEL_ID:
        return

    email = await build_email(message)
    await asyncio.to_thread(send_email, email)
    print(f"Forwarded message {message.id} from #{message.channel.name} to email")


client.run(DISCORD_BOT_TOKEN)
