# a small MCP server with one tool, send_email, that sends through gmail smtp (task 4)
# protocol messages go on stdout and all logging on stderr; the password is never printed

import logging
import os
import smtplib
import ssl
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

# .env sits in the repo root, found from this file so the working directory doesn't matter
ENV_FILE=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
SMTP_HOST='smtp.gmail.com'
SMTP_PORT=587

# stdout belongs to the protocol, so logs only ever go to stderr
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='gmail_server: %(message)s')
log=logging.getLogger('gmail_server')

mcp=MCPServer('gmail', instructions='Send an email through Gmail SMTP with the send_email tool.')


def read_env_file(path):
    """KEY=VALUE pairs from a .env file; a missing file gives an empty dict."""
    values={}
    if not os.path.exists(path):
        return values
    with open(path, encoding='utf-8') as f:
        for line in f:
            line=line.strip()
            if line=='' or line.startswith('#') or '=' not in line:
                continue
            key, value=line.split('=', 1)
            values[key.strip()]=value.strip().strip('"').strip("'")
    return values


def load_credentials():
    """Gmail address and app password from the environment first, then from .env."""
    from_file=read_env_file(ENV_FILE)
    address=os.environ.get('GMAIL_ADDRESS') or from_file.get('GMAIL_ADDRESS', '')
    password=os.environ.get('GMAIL_APP_PASSWORD') or from_file.get('GMAIL_APP_PASSWORD', '')
    # google shows app passwords as four groups of four, the spaces aren't part of it
    password=password.replace(' ', '')
    return address, password


def build_message(sender, to, subject, body, references, intended_recipient):
    """The email itself, with Date, Message-ID, References and X-Intended-Recipient set here."""
    message=EmailMessage()
    message['From']=sender
    message['To']=to
    message['Subject']=subject
    message['Date']=format_datetime(datetime.now(timezone.utc))
    message['Message-ID']=make_msgid(domain=sender.split('@')[-1])
    if references:
        message['References']=references
    if intended_recipient:
        message['X-Intended-Recipient']=intended_recipient
    message.set_content(body)
    return message


@mcp.tool()
def send_email(to: str, subject: str, body: str, references: str = '', intended_recipient: str = '') -> dict[str, str]:
    """Send a plain-text email through Gmail SMTP. references sets the References header and
    intended_recipient the X-Intended-Recipient header. Returns the status and the new Message-ID."""
    sender, password=load_credentials()
    if sender=='' or password=='':
        raise ToolError('not sent: GMAIL_ADDRESS and GMAIL_APP_PASSWORD are not set in the environment or in '+ENV_FILE)
    if '@' not in to:
        raise ToolError('not sent: "to" is not an email address: '+to)
    try:
        message=build_message(sender, to, subject, body, references, intended_recipient)
    except Exception as e:
        raise ToolError('not sent: could not build the message: %s: %s' % (type(e).__name__, e))
    log.info('sending to %s, subject %r', to, subject)
    try:
        server=smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
        try:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
            server.login(sender, password)
            server.send_message(message)
        finally:
            server.quit()
    except Exception as e:
        # smtplib errors carry the server's reply, never the password
        log.info('send failed: %s: %s', type(e).__name__, e)
        raise ToolError('not sent: %s: %s' % (type(e).__name__, e))
    log.info('sent, Message-ID %s', message['Message-ID'])
    return {'status': 'sent', 'to': to, 'message_id': message['Message-ID'], 'date': message['Date']}


if __name__=='__main__':
    mcp.run()
