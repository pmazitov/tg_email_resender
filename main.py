import json
import requests
import urllib
import time
from collections import defaultdict
import email
import imaplib
import sys
from pony import orm

db = orm.Database()
class Chats(db.Entity):
    chat_id = orm.PrimaryKey(int)
    state = orm.Required(int)
    login = orm.Optional(str)
    passwd = orm.Optional(str)
db.bind(provider='sqlite', filename=':memory:')
db.generate_mapping(create_tables=True)


TOKEN = "5295625360:AAH5BaLlkwmC4iIRFbusIMSPREhaehbWykk"
URL = "https://api.telegram.org/bot{}/".format(TOKEN)


def get_url(url):
    response = requests.get(url)
    content = response.content.decode("utf8")
    return content


def get_json_from_url(url):
    content = get_url(url)
    js = json.loads(content)
    return js

def get_updates(offset=None):
    url = URL + "getUpdates?timeout=10"
    if offset:
        url += "&offset={}".format(offset)
    js = get_json_from_url(url)
    return js

def group_updates(updates):
    grouped_updates = defaultdict(lambda: [])
    for update in updates["result"]:
        message_update = update.get("message")
        if message_update:
            chat = message_update["chat"]["id"]
            grouped_updates[chat] += [update]
    return grouped_updates

def get_last_update_id(updates):
    update_ids = []
    for update in updates["result"]:
        update_ids.append(int(update["update_id"]))
    return max(update_ids)

def send_message(text, chat_id):
    text = urllib.parse.quote_plus(text)
    url = URL + "sendMessage?text={}&chat_id={}".format(text, chat_id)
    get_url(url)

def get_new_emails(imap_login, imap_password):
    ix = imap_login.index('@')
    EMAIL = imap_login
    PASSWORD = imap_password
    SERVER = 'imap.' + imap_login[ix + 1:]

    mail = imaplib.IMAP4_SSL(SERVER)
    mail.login(EMAIL, PASSWORD)
    mail.select('inbox', readonly=False)

    status, data = mail.search(None, 'UNSEEN')
    mail_ids = []
    for block in data:
        mail_ids += block.split()

    result = []

    for i in mail_ids:
        status, data = mail.fetch(i, '(RFC822)')

        for response_part in data:
            if isinstance(response_part, tuple):
                message = email.message_from_bytes(response_part[1])
                typ, data = mail.store(i, '+FLAGS', '\\Deleted')

                mail_from = message['from']
                mail_subject = message['subject']

                if message.is_multipart():
                    mail_content = ''
                    for part in message.get_payload():
                        if part.get_content_type() == 'text/plain':
                            mail_content += part.get_payload()
                else:
                    mail_content = message.get_payload()

                result += [{'from': mail_from, 'subj': mail_subject,
                            'content': mail_content}]
    mail.close()
    return result

@orm.db_session()
def handle_updates(grouped_updates):
    for chat_id, g_upd in grouped_updates.items():
        current_chat = Chats.get(chat_id=chat_id)
        current_state = current_chat.state if current_chat else 0
        current_login = current_chat.login if current_chat else None
        current_passwd = current_chat.passwd if current_chat else None
        for upd in g_upd:
            text = upd["message"]["text"]
            if text == "/start":
                start_message = """Welcome to Emails in Telegram bot!
It allows you to receive email from your different
mailboxes right into this Telegram chat.

To add a mailbox you want to receive messages from send /new."""

                send_message(start_message, chat_id)
            elif text == "/new":
                current_state = 1
                Chats(chat_id=chat_id, state=current_state)
                send_message('Enter your email', chat_id)
            elif current_state == 1:
                current_chat.state = 2
                current_chat.login = text
                send_message('Enter your password', chat_id)
            elif current_state == 2:
                current_chat.state = 0
                current_chat.passwd = text
                send_message('Done!', chat_id)


@orm.db_session()
def main():
    last_update_id = None
    while True:
        updates = get_updates(last_update_id)
        if len(updates["result"]) > 0:
            last_update_id = get_last_update_id(updates) + 1
            grouped_updates = group_updates(updates)
            handle_updates(grouped_updates)
        to_broadcast = orm.select(c for c in Chats)[:]
        for c in to_broadcast:
            res = []
            fail_respond = None
            if c.login and c.passwd:
                try:
                    res = get_new_emails(c.login, c.passwd)
                except Exception:
                    fail_respond = '''You entered invalid credentials.

Try send /new and enter valid credentials again'''

            if fail_respond:
                send_message(fail_respond, c.chat_id)
                c.delete()
            else:
                for e in res:
                    send_message(e['content'], c.chat_id)
        time.sleep(0.5)

if __name__ == '__main__':
    main()
