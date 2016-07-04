#!/usr/bin/env python2.7
"""
Acts as a server for RPI, checks wifi connection, checks reddit messages

LAST UPDATED: 26 JUN 2016
"""
from time import sleep
import os
import sys
import datetime
import subprocess
import traceback
import logging
import logging.handlers
import urllib2
import praw


def check_messages(r):
    """
    Checks messages
    :return: mnt,wnt = True if they are playing today
    """
    logging.info('Checking messages')
    mnt, wnt = False, False
    for msg in r.get_unread(unset_has_mail=True, update_user=True, limit=None):
        if 'Pi command' in msg.subject:
            msg.mark_as_read()
            logging.info('Pi command found in a PM!')
            if 'quit' in msg.body.lower():
                logging.warning("Shutting down per Pi command!")
                # os._exit(-1)
                sys.exit()
        elif 'MNT next match' in msg.subject:
            msg.mark_as_read()
            path = '/media/usb/Server/mnt.txt'
            with open(path, 'w') as filep:
                filep.write(msg.body)
            logging.info('Wrote MNT next match file')

        elif 'MNT match today' in msg.subject:
            msg.mark_as_read()
            mnt = True

        elif 'WNT next match' in msg.subject:
            msg.mark_as_read()
            path1 = '/media/usb/Server/wnt.txt'
            with open(path1, 'w') as filep:
                filep.write(msg.body)
            logging.info('Wrote WNT next match file')

        elif 'WNT match today' in msg.subject:
            msg.mark_as_read()
            wnt = True

        elif 'match thread' in msg.subject.lower() and 'r3d' not in msg.subject.lower():
            msg.mark_as_read()
            m = "This bot is for /r/ussoccer only. Please send your request to u/MatchThreadder (two d's) instead."
            msg.reply(m)

        elif 'poke' in msg.subject.lower() or 'poke' in msg.body.lower():
            msg.mark_as_read()
            msg.reply("I'm alive server.py!")
            logging.info("I got poked!")

    return mnt, wnt


def mnt_matchthread():
    path = '/media/usb/Server/mnt.txt'
    now = datetime.datetime.now()
    with open(path) as filep:  # TODO if 'Unable' in filep ???
        m_opponent, m_venue, m_date, m_watch, m_time = filep.read().split('?')

    if 'P' in m_time and '12' not in m_time:
        kickoff = int(m_time[:m_time.index(':')]) + 12
    else:
        kickoff = int(m_time[:m_time.index(':')])

    start_time = kickoff - 1

    if start_time == now.hour:
        # TODO create a match thread program for MNT
        args = "source /home/pi/pytwo/bin/activate; sleep 1s; python /media/usb/Server/MatchThreader/matchthread.py"
        logging.info('Creating MNT vs %s match thread for %sPM', m_opponent, kickoff)
        subprocess.call(args, shell=True, stdout=subprocess.PIPE)


def wnt_matchthread(r):
    path = '/media/usb/Server/wnt.txt'
    now = datetime.datetime.now()
    with open(path) as filep:  # TODO if 'Unable' in filep ???
        w_opponent, w_venue, w_date, w_watch, w_time = filep.read().split('?')

    if 'P' in w_time and '12' not in w_time:
        kickoff = int(w_time[:w_time.index(':')]) + 12
    else:
        kickoff = int(w_time[:w_time.index(':')])

    start_time = kickoff - 1

    if start_time == now.hour:
        # TODO create a match thread program for WNT, see if goal.com has the game
        args = "source /home/pi/pytwo/bin/activate; sleep 1s; python /media/usb/Server/MatchThreader/matchthread.py"
        logging.info('Creating WNT vs %s match thread for %sPM', w_opponent, start_time)
        subprocess.call(args, shell=True, stdout=subprocess.PIPE)
        body = '**International Friendly**\n\n---\n\n' \
               '**Opponent:** {}\n\n---\n\n**Available on:** {}\n\n---\n\n**Lineup:** TBD'.format(w_opponent, w_watch)
        title_text = 'Match Thread: WNT vs {} [kickoff {} ET]'.format(w_opponent, w_time)
        r.submit('ussoccer', title_text, text=body, send_replies=False)


def check_wifi():
    """
    Checks for Wifi connectivity
    :return: True if connected to wifi
    """
    # Try wifi Python library?
    # http://stackoverflow.com/questions/20470626/python-script-for-raspberrypi-to-connect-wifi-automatically
    try:
        urllib2.urlopen("http://www.google.com").close()
    except urllib2.URLError:
        logging.info('Not connected to the internet, sleeping for 120 seconds')
        sleep(120)


def start():
    running = True
    # start logging stuff
    path12 = os.getcwd()
    os.chdir('/media/usb/Server/')
    logging.basicConfig(format='%(asctime)s %(message)s', datefmt='%m/%d/%Y %I:%M:%S %p',
                        filename='log.log', level=logging.INFO)
    os.chdir(path12)
    with open('/media/usb/Server/MatchThreader/.ussoccer.txt') as filep:
        secret_key, refresh_token, access, __ = filep.read().split('\n')
    user_agent = "/r/ussoccer RPI server v2.6 by RedRavens"
    r = praw.Reddit(user_agent, oauth_client_id='_3vsO2wedhIMtw',
                    oauth_client_secret=secret_key,
                    oauth_redirect_uri='http://127.0.0.1:65010/authorize_callback')

    access_information = {'access_token': access,
                          'refresh_token': refresh_token,
                          'scope': {'account creddits edit flair history identity livemanage modconfig '
                                    'modcontributors modflair modlog modothers modposts modself modwiki '
                                    'mysubreddits privatemessages read '
                                    'report save submit subscribe vote wikiedit wikiread'}
                          }
    access = r.refresh_access_information(access_information['refresh_token'])
    r.set_access_credentials(**access)
    logging.info('Logged into reddit')

    while running:
        try:
            check_wifi()
            mnt_matchtoday, wnt_matchtoday = check_messages(r)

            if mnt_matchtoday or wnt_matchtoday:
                # mnt_matchthread()
                # wnt_matchthread(r)
                args = "source /home/pi/pytwo/bin/activate; sleep 1s; " \
                       "python /media/usb/Server/MatchThreader/matchthread.py &"
                logging.info('Creating match thread for today')
                subprocess.call(args, shell=True, stdout=subprocess.PIPE)
                sleep(60)
            else:
                sleep(180)
                sys.exit()
        except KeyboardInterrupt:
            running = False
            logging.info('Keyboard interrupt')
        except Exception as e:
            logging.error('ERROR: %s; %s', e, traceback.format_exc())


if __name__ == '__main__':
    start()
