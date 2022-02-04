import json
import requests
import urllib
import time
from collections import defaultdict
import email
import imaplib
import sys
from pony import orm
import quopri


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
    if imap_login[ix + 1:] == 'bk.ru':
        SERVER = 'imap.mail.ru'
    elif imap_login[ix + 1:] == 'phystech.edu':
        SERVER = 'imap.gmail.com'
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
                typ, data = mail.store(i, '+FLAGS', '\\Seen')

                from_ = email.header.decode_header(message['from'])[0]
                mail_from = from_[0].decode(from_[1], 'replace') \
                    if from_[1] else from_[0]
                subject_ = email.header.decode_header(message['subject'])[0]
                mail_subject = subject_[0].decode(subject_[1], 'replace') \
                    if subject_[1] else subject[0]

                if message.is_multipart():
                    mail_content = ''
                    for part in message.get_payload():
                        if part.get_content_type() == 'text/plain':
                            payload_bytes = part.get_payload(decode=True)
                            charset = part.get_content_charset('utf-8')
                            mail_content += payload_bytes\
                                .decode(charset, 'replace')
                else:
                    charset = message.get_charset('utf-8')
                    mail_content = message.get_payload(decode=True)\
                        .decode(charset, 'replace')


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
            if text == "/start" and current_state == 0:
                start_message = """Welcome to Emails2Telegram bot!
It allows you to receive emails from your \
mailbox right into this Telegram chat.

To add a mailbox you want to receive messages from send /new

To stop receive messages from current active mailbox send /stop"""

                send_message(start_message, chat_id)
            elif text == "/new" and current_state == 0:
                current_state = 1
                if not current_chat:
                    Chats(chat_id=chat_id, state=current_state)
                else:
                    current_chat.state = current_state
                send_message('Enter your email', chat_id)
            elif current_chat and current_state == 1:
                current_chat.state = 2
                current_chat.login = text
                mes = '''Enter your APPLICATION password
(google how to generate application password for your mailbox)'''
                send_message(mes, chat_id)
            elif current_chat and current_state == 2:
                current_chat.state = 0
                current_chat.passwd = text
                send_message('Done!', chat_id)
            elif text == '/stop' and  current_state == 0:
                if current_chat:
                    current_chat.delete()
                mes = '''Your mailbox is disconnected from the chatbot now.

To connect the chatbot to your mailbox again send /new'''
                send_message(mes, chat_id)


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
                except Exception as e:
                    fail_respond = '''You entered invalid credentials

Make sure that you entered application password and not human one,\
google how to generate application password for your mailbox.

Try send /new and enter valid credentials again'''
                    print(e)

            if fail_respond:
                send_message(fail_respond, c.chat_id)
                c.delete()
            else:
                for e in res:
                    respond = '''From: {0}
Subject: {1}
-------------------

{2}'''.format(e['from'], e['subj'], e['content'])
                    send_message(respond, c.chat_id)
        orm.commit()
        time.sleep(0.5)

if __name__ == '__main__':
    main()
