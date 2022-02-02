import json
import requests
import urllib
import time
from collections import defaultdict
import email
import imaplib
import sys
import sqlalchemy as db


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
    url = URL + "getUpdates?timeout=3"
    if offset:
        url += "&offset={}".format(offset)
    js = get_json_from_url(url)
    return js

def group_updates(updates):
    grouped_updates = defaultdict(lambda: [])
    for update in updates["result"]:
        chat = update["message"]["chat"]["id"]
        grouped_updates[chat] += [update]
    return grouped_updates

def get_last_update_id(updates):
    update_ids = []
    for update in updates["result"]:
        update_ids.append(int(update["update_id"]))
    return max(update_ids)

def get_last_chat_id_and_text(updates):
    num_updates = len(updates["result"])
    last_update = num_updates - 1
    text = updates["result"][last_update]["message"]["text"]
    chat_id = updates["result"][last_update]["message"]["chat"]["id"]
    return (text, chat_id)

def send_message(text, chat_id):
    text = urllib.parse.quote_plus(text)
    url = URL + "sendMessage?text={}&chat_id={}".format(text, chat_id)
    get_url(url)

def get_new_emails(imap_login, imap_password):
    ix = imap_login.index('@')
    EMAIL = imap_login
    PASSWORD = imap_password
    SERVER = 'imap.' + imap_login[ix + 1:]

    # connect to the server and go to its inbox
    mail = imaplib.IMAP4_SSL(SERVER)
    mail.login(EMAIL, PASSWORD)
    # we choose the inbox but you can select others
    mail.select('inbox', readonly=False)

    # we'll search using the ALL criteria to retrieve
    # every message inside the inbox
    # it will return with its status and a list of ids
    status, data = mail.search(None, 'UNSEEN')
    # the list returned is a list of bytes separated
    # by white spaces on this format: [b'1 2 3', b'4 5 6']
    # so, to separate it first we create an empty list
    mail_ids = []
    # then we go through the list splitting its blocks
    # of bytes and appending to the mail_ids list
    for block in data:
        # the split function called without parameter
        # transforms the text or bytes into a list using
        # as separator the white spaces:
        # b'1 2 3'.split() => [b'1', b'2', b'3']
        mail_ids += block.split()

    result = []

    # now for every id we'll fetch the email
    # to extract its content
    for i in mail_ids:
        # the fetch function fetch the email given its id
        # and format that you want the message to be
        status, data = mail.fetch(i, '(RFC822)')

        # the content data at the '(RFC822)' format comes on
        # a list with a tuple with header, content, and the closing
        # byte b')'
        for response_part in data:
            # so if its a tuple...
            if isinstance(response_part, tuple):
                # we go for the content at its second element
                # skipping the header at the first and the closing
                # at the third
                message = email.message_from_bytes(response_part[1])
                typ, data = mail.store(i, '+FLAGS', '\\Deleted')

                # with the content we can extract the info about
                # who sent the message and its subject
                mail_from = message['from']
                mail_subject = message['subject']

                # then for the text we have a little more work to do
                # because it can be in plain text or multipart
                # if its not plain text we need to separate the message
                # from its annexes to get the text
                if message.is_multipart():
                    mail_content = ''

                    # on multipart we have the text message and
                    # another things like annex, and html version
                    # of the message, in that case we loop through
                    # the email payload
                    for part in message.get_payload():
                        # if the content type is text/plain
                        # we extract it
                        if part.get_content_type() == 'text/plain':
                            mail_content += part.get_payload()
                else:
                    # if the message isn't multipart, just extract it
                    mail_content = message.get_payload()

                # and then let's show its result
                result += [{'from': mail_from, 'subj': mail_subject,
                            'content': mail_content}]
    mail.close()
    return result

def handle_updates(grouped_updates, engine):
    for chat_id, g_upd in grouped_updates.items():
        print(chat_id)
        res = engine.execute('SELECT state FROM main_db\
                              WHERE chat_id = {0}'.format(chat_id)).first()
        current_state = res[0] if res else 0
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
                engine.execute('INSERT INTO "main_db"'
                               '(chat_id, state, login, passwd)'
                               'VALUES ({0}, {1}, NULL, NULL)'\
                                   .format(chat_id, current_state))
                send_message('Enter your email', chat_id)
            elif current_state == 1:
                current_state = 2
                engine.execute(f'DELETE from "main_db" where chat_id={chat_id};')
                engine.execute('INSERT INTO "main_db"'
                               '(chat_id, state, login, passwd)'
                               'VALUES ({0}, {1}, NULL, NULL)'\
                                   .format(chat_id, current_state))

                # engine.execute('UPDATE "main_db"'
                #                'SET login = {0}, state = {1}'
                #                'WHERE chat_id = {2}'\
                #                    .format(text, current_state, chat_id))
                send_message('Enter your password', chat_id)
            elif current_state == 2:
                current_state = 0
                # engine.execute('UPDATE "main_db"'
                #                'SET login = {0}, state = {1}'
                #                'WHERE chat_id = {2}'\
                #                    .format(text, current_state, chat_id))
                send_message('Done!', chat_id)

def get_engine():
    engine = db.create_engine("sqlite:///email_resender_engine.db")
    metadata = db.MetaData(engine)
    db.Table('main_db', metadata,
          db.Column('chat_id', db.Integer, primary_key=True, nullable=False),
          db.Column('state', db.Integer),
          db.Column('login', db.String),
          db.Column('passwd', db.String))
    metadata.create_all()
    return engine

def main():
    engine = get_engine()
    last_update_id = None
    while True:
        updates = get_updates(last_update_id)
        if len(updates["result"]) > 0:
            last_update_id = get_last_update_id(updates) + 1
            grouped_updates = group_updates(updates)
            handle_updates(grouped_updates, engine)
            res = get_new_emails('miheevalge@gmail.com', 'sber7nado8menjatj9')
            send_message(res[0]['content'], 128964788)
        time.sleep(0.5)

if __name__ == '__main__':
    main()
