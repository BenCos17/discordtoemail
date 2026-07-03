import asyncio
from dataclasses import dataclass
import mimetypes
import os
import smtplib
from email.message import EmailMessage
from typing import Optional

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
GROUP_WINDOW_SECONDS = int(os.getenv("GROUP_WINDOW_SECONDS", "300"))


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


@dataclass
class ForwardAttachment:
    filename: str
    content_type: str
    data: bytes


@dataclass
class ForwardEntry:
    channel_name: str
    guild_name: str
    author_name: str
    author_display: str
    timestamp: str
    message_id: int
    jump_url: str
    content: str
    attachments: list[ForwardAttachment]
    forwarded_sections: list[str]


intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

pending_entries: list[ForwardEntry] = []
flush_task: Optional[asyncio.Task[None]] = None
buffer_lock = asyncio.Lock()


def build_attachment_line(attachment: ForwardAttachment) -> str:
    return f"- {attachment.filename}"


async def create_forward_entry(message: discord.Message) -> ForwardEntry:
    attachments: list[ForwardAttachment] = []
    for attachment in message.attachments:
        file_bytes = await attachment.read()
        content_type = attachment.content_type or mimetypes.guess_type(attachment.filename)[0] or "application/octet-stream"
        attachments.append(
            ForwardAttachment(
                filename=attachment.filename,
                content_type=content_type,
                data=file_bytes,
            )
        )

    forwarded_sections: list[str] = []
    snapshots = list(getattr(message, "message_snapshots", []))
    for index, snapshot in enumerate(snapshots, start=1):
        snapshot_attachments: list[ForwardAttachment] = []
        for attachment in snapshot.attachments:
            file_bytes = await attachment.read()
            content_type = attachment.content_type or mimetypes.guess_type(attachment.filename)[0] or "application/octet-stream"
            snapshot_attachments.append(
                ForwardAttachment(
                    filename=attachment.filename,
                    content_type=content_type,
                    data=file_bytes,
                )
            )

        snapshot_attachment_lines = "\n".join(build_attachment_line(attachment) for attachment in snapshot_attachments)
        if not snapshot_attachment_lines:
            snapshot_attachment_lines = "None"

        forwarded_sections.append(
            f"Forwarded message {index}:\n"
            f"  Type: {snapshot.type}\n"
            f"  Created: {snapshot.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"  Content: {snapshot.content or '[no text content]'}\n"
            f"  Attachments:\n{snapshot_attachment_lines}"
        )

        attachments.extend(snapshot_attachments)

    return ForwardEntry(
        channel_name=message.channel.name,
        guild_name=message.guild.name if message.guild else "Direct Message",
        author_name=message.author.display_name,
        author_display=str(message.author),
        timestamp=message.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        message_id=message.id,
        jump_url=message.jump_url,
        content=message.content or "[no text content]",
        attachments=attachments,
        forwarded_sections=forwarded_sections,
    )


def build_email(entries: list[ForwardEntry]) -> EmailMessage:
    email = EmailMessage()
    entries = sorted(entries, key=lambda entry: entry.message_id)
    first_entry = entries[0]
    if len(entries) > 1:
        subject = f"{EMAIL_SUBJECT_PREFIX}: #{first_entry.channel_name} - {first_entry.author_name} (+{len(entries) - 1} more)"
    else:
        subject = f"{EMAIL_SUBJECT_PREFIX}: #{first_entry.channel_name} - {first_entry.author_name}"

    body_sections = []
    for index, entry in enumerate(entries, start=1):
        attachment_names = "\n".join(build_attachment_line(attachment) for attachment in entry.attachments)
        if not attachment_names:
            attachment_names = "None"

        forwarded_text = "\n\n".join(entry.forwarded_sections) if entry.forwarded_sections else "None"

        body_sections.append(
            f"Message {index}:\n"
            f"Channel: #{entry.channel_name}\n"
            f"Server: {entry.guild_name}\n"
            f"Author: {entry.author_name} ({entry.author_display})\n"
            f"Time: {entry.timestamp}\n"
            f"Message ID: {entry.message_id}\n"
            f"Link: {entry.jump_url}\n\n"
            f"Content:\n{entry.content}\n\n"
            f"Attachments:\n{attachment_names}\n"
            f"\nForwarded snapshots:\n{forwarded_text}\n"
        )

    email["From"] = EMAIL_FROM
    email["To"] = ", ".join(EMAIL_TO)
    email["Subject"] = subject
    email.set_content("\n\n".join(body_sections))

    for entry in entries:
        for attachment in entry.attachments:
            maintype, subtype = attachment.content_type.split("/", 1)
            email.add_attachment(
                attachment.data,
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


async def flush_pending_entries() -> None:
    global flush_task

    try:
        await asyncio.sleep(GROUP_WINDOW_SECONDS)
    except asyncio.CancelledError:
        return

    async with buffer_lock:
        entries = list(pending_entries)
        pending_entries.clear()
        flush_task = None

    if not entries:
        return

    email = build_email(entries)
    await asyncio.to_thread(send_email, email)
    print(f"Forwarded {len(entries)} message(s) from #{entries[0].channel_name} to email")


async def queue_forward(message: discord.Message) -> None:
    global flush_task

    entry = await create_forward_entry(message)
    async with buffer_lock:
        pending_entries.append(entry)
        if flush_task is not None and not flush_task.done():
            flush_task.cancel()
        flush_task = asyncio.create_task(flush_pending_entries())


@client.event
async def on_ready() -> None:
    print(f"Logged in as {client.user} and watching channel {SOURCE_CHANNEL_ID}")


@client.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot:
        return
    if message.channel.id != SOURCE_CHANNEL_ID:
        return

    await queue_forward(message)
    print(f"Queued message {message.id} from #{message.channel.name}")


client.run(DISCORD_BOT_TOKEN)
