###################################
#    LAST UPDATED: 26 JUNE 2016   #
###################################
import praw
import urllib2
import re
import sys
import os
import logging
import logging.handlers
import json
import cookielib
import datetime
import requests
import requests.auth
import traceback
from twilio.rest import TwilioRestClient
from collections import Counter
from time import sleep


def get_timestamp():
    dt = str(datetime.datetime.now().month) + '/' + str(datetime.datetime.now().day) + ' '
    hr = str(datetime.datetime.now().hour) if len(str(datetime.datetime.now().hour)) > 1 \
        else '0' + str(datetime.datetime.now().hour)
    min_ = str(datetime.datetime.now().minute) if len(str(datetime.datetime.now().minute)) > 1 \
        else '0' + str(datetime.datetime.now().minute)
    t = '[' + hr + ':' + min_ + '] '
    return dt + t


# save activeThreads
def save_data():
    f = open('active_threads.txt', 'w+')
    s = ''
    for data in activeThreads:
        matchid, t1, t2, thread_id, reqr, sub = data
        s += matchid + '####' + t1 + '####' + t2 + '####' + thread_id + '####' + reqr + '####' + sub + '&&&&'
    s = s[0:-4]  # take off last &&&&
    f.write(s.encode('utf8'))
    f.close()


# read saved activeThreads data 
def read_data():
    f = open('active_threads.txt', 'a+')
    s = f.read().decode('utf8')
    info = s.split('&&&&')
    if info[0] != '':
        for d in info:
            [matchid, t1, t2, thread_id, reqr, sub] = d.split('####')
            matchid = matchid.encode('utf8')  # get rid of weird character at start -
            # got to be a better way to do this...
            data = matchid, t1, t2, thread_id, reqr, sub
            activeThreads.append(data)
            logger.info("Active threads: %i - added %s vs %s (/r/%s)", len(activeThreads), t1, t2, sub)
            print '{}Active threads: {} - added {} vs {} (/r/{})'.format(get_timestamp(), len(activeThreads), t1,
                                                                         t2, sub)
    f.close()


def get_bot_status():
    thread = r.get_submission(submission_id='22ah8i')
    status = re.findall('bar-10-(.*?)\)', thread.selftext)
    msg = re.findall('\| \*(.*?)\*', thread.selftext)
    return status[0], msg[0]


def find_goal_site(team1, team2):
    # search for each word in each team name in goal.com's fixture list, return most frequent result
    t1 = team1.split()
    t2 = team2.split()
    linklist = []
    # browser header (to avoid 405 error with goal.com, streaming sites)
    hdr1 = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.11 '
                         '(KHTML, like Gecko) Chrome/23.0.1271.64 Safari/537.11',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.3',
            'Accept-Encoding': 'none',
            'Accept-Language': 'en-US,en;q=0.8',
            'Connection': 'keep-alive'}
    fixaddress = "http://www.goal.com/en-us/live-scores"
    req = urllib2.Request(fixaddress, headers=hdr1)
    fixwebsite = urllib2.urlopen(req)
    fix_html = fixwebsite.read()
    links = re.findall('/en-us/match/(.*?)"', fix_html)
    for link in links:
        for word in t1:
            if link.find(word.lower()) != -1:
                linklist.append(link)
        for word in t2:
            if link.find(word.lower()) != -1:
                linklist.append(link)
    counts = Counter(linklist)
    if counts.most_common(1):
        mode = counts.most_common(1)[0]
        return mode[0]
    else:
        return 'no match'


def get_lineups(matchid):
    # try to find line-ups (404 if line-ups not on goal.com yet)
    try:
        lineaddress = "http://www.goal.com/en-us/match/" + matchid + "/lineups"
        req = urllib2.Request(lineaddress, headers=hdr)
        linewebsite = urllib2.urlopen(req)
        line_html_enc = linewebsite.read()
        line_html = line_html_enc.decode("utf8")

        delim__ = '<ul class="player-list">'
        split = line_html.split(delim__)  # [0]:nonsense [1]:t1 XI [2]:t2 XI [3]:t1 subs [4]:t2 subs + managers

        manager_delim = '<div class="manager"'
        split[4] = split[4].split(manager_delim)[0]  # managers now excluded

        team1start = re.findall('<span class="name".*?>(.*?)<', split[1], re.DOTALL)
        team2start = re.findall('<span class="name".*?>(.*?)<', split[2], re.DOTALL)
        team1sub = re.findall('<span class="name".*?>(.*?)<', split[3], re.DOTALL)
        team2sub = re.findall('<span class="name".*?>(.*?)<', split[4], re.DOTALL)

        # if no players found, ie TBA
        if not team1start:
            team1start = ["TBA"]
        if not team1sub:
            team1sub = ["TBA"]
        if not team2start:
            team2start = ["TBA"]
        if not team2sub:
            team2sub = ["TBA"]
        return team1start, team1sub, team2start, team2sub

    except urllib2.HTTPError:
        team1start = ["TBA"]
        team1sub = ["TBA"]
        team2start = ["TBA"]
        team2sub = ["TBA"]
        return team1start, team1sub, team2start, team2sub


# get current match time/status
def get_status(matchid):
    lineaddress = "http://www.goal.com/en-us/match/" + matchid
    req = urllib2.Request(lineaddress, headers=hdr)
    linewebsite = urllib2.urlopen(req)
    line_html = linewebsite.read()
    status = re.findall('<div class="vs">(.*?)<', line_html, re.DOTALL)[0]
    return status


# get venue, ref, lineups, etc from goal.com    
def get_gdc_info(matchid_):
    lineaddress = "http://www.goal.com/en-us/match/" + matchid_
    req = urllib2.Request(lineaddress, headers=hdr)
    linewebsite = urllib2.urlopen(req)
    line_html_enc = linewebsite.read()
    line_html = line_html_enc.decode("utf8")

    # get "fixed" versions of team names (ie team names from goal.com, not team names from match thread request)
    team1fix = re.findall('<div class="home" .*?<h2>(.*?)<', line_html, re.DOTALL)[0]
    team2fix = re.findall('<div class="away" .*?<h2>(.*?)<', line_html, re.DOTALL)[0]

    if team1fix[-1] == ' ':
        team1fix = team1fix[0:-1]
    if team2fix[-1] == ' ':
        team2fix = team2fix[0:-1]

    status = get_status(matchid_)
    ko = re.findall('<div class="match-header .*?</li>.*? (.*?)</li>', line_html, re.DOTALL)[0]

    venue = re.findall('<div class="match-header .*?</li>.*?</li>.*? (.*?)</li>', line_html, re.DOTALL)
    if venue:
        venue = venue[0]
    else:
        venue = '?'

    ref = re.findall('Referee: (.*?)</li>', line_html, re.DOTALL)
    if ref:
        ref = ref[0]
    else:
        ref = '?'

    team1start, team1sub, team2start, team2sub = get_lineups(matchid_)

    return team1fix, team2fix, team1start, team1sub, team2start, team2sub, venue, ref, ko, status


def write_lineups(body, t1, t2, team1start, team1sub, team2start, team2sub):
    body += '**LINE-UPS**\n\n**' + t1 + '**:\n\n'
    body += ", ".join(x for x in team1start) + ".\n\n"
    body += '**Subs:** '
    body += ", ".join(x for x in team1sub) + ".\n\n^____________________________\n\n"

    body += '**' + t2 + '**:\n\n'
    body += ", ".join(x for x in team2start) + ".\n\n"
    body += '**Subs:** '
    body += ", ".join(x for x in team2sub) + "."
    return body


def find_scores_side(time, left, right):
    lefttimes = [int(x) for x in re.findall(r'\b\d+\b', left)]
    righttimes = [int(x) for x in re.findall(r'\b\d+\b', right)]
    if time in lefttimes and time in righttimes:
        return 'none'
    if time in lefttimes:
        return 'left'
    if time in righttimes:
        return 'right'
    return 'none'


def grab_events(matchID, left, right):
    lineAddress = "http://www.goal.com/en-us/match/" + matchID + "/live-commentary"
    lineWebsite = requests.get(lineAddress, timeout=15)
    line_html = lineWebsite.text
    try:
        if lineWebsite.status_code == 200:
            body = ""
            split = line_html.split('<ul class="commentaries')  # [0]:nonsense [1]:events
            events = split[1].split('<li data-event-type="')
            events = events[1:]
            events = events[::-1]

            L = 0
            R = 0
            updatescores = True

            # goal.com's full commentary tagged as "action" - ignore these
            # will only report goals (+ penalties, own goals), yellows, reds, subs - not sure what else goal.com reports
            supportedEvents = ['goal', 'penalty-goal', 'own-goal', 'missed-penalty', 'yellow-card', 'red-card',
                               'yellow-red', 'substitution']
            for text in events:
                tag = re.findall('(.*?)"', text, re.DOTALL)[0]
                if tag.lower() in supportedEvents:
                    time = re.findall('<div class="time">\n?(.*?)<', text, re.DOTALL)[0]
                    time = time.strip()
                    info = "**" + time + "** "
                    event = re.findall('<div class="text">\n?(.*?)<', text, re.DOTALL)[0]
                    if event[-1] == ' ':
                        event = event[:-1]
                    if tag.lower() == 'goal' or tag.lower() == 'penalty-goal' or tag.lower() == 'own-goal':
                        if tag.lower() == 'goal':
                            event = event[:4] + ' ' + event[4:]
                            info += '[](/goal) **' + event + '**'
                        elif tag.lower() == 'penalty-goal':
                            event = event[:12] + ' ' + event[12:]
                            info += '[](/goal) **' + event + '**'
                        else:
                            event = event[:8] + ' ' + event[8:]
                            info += '[](/goal) **' + event + '**'
                        if find_scores_side(int(time.split("'")[0]), left, right) == 'left':
                            L += 1
                        elif find_scores_side(int(time.split("'")[0]), left, right) == 'right':
                            R += 1
                        else:
                            updatescores = False
                        if updatescores:
                            info += ' **' + str(L) + '-' + str(R) + '**'
                    if tag.lower() == 'missed-penalty':
                        event = event[:14] + ' ' + event[14:]
                        info += '[](/own-goal) **' + event + '**'
                    if tag.lower() == 'yellow-card':
                        event = event[:11] + ' ' + event[11:]
                        info += '[](/yellow) ' + event
                    if tag.lower() == 'red-card':
                        event = event[:8] + ' ' + event[8:]
                        info += '[](/red) ' + event
                    if tag.lower() == 'yellow-red':
                        event = event[:10] + ' ' + event[10:]
                        info += '[](/second-yellow) ' + event
                    if tag.lower() == 'substitution':
                        info += '[](/sub) Substitution: [](/down)' + \
                                re.findall('"sub-out">(.*?)<', text, re.DOTALL)[0]
                        info += ' [](/up)' + re.findall('"sub-in">(.*?)<', text, re.DOTALL)[0]
                    body += info + '\n\n'

            return body

        else:
            return ""
    except:
        return ""

'''

def grab_events(matchID, left, right):
    lineAddress = "http://www.goal.com/en-us/match/" + matchID + "/live-commentary"
    #	print getTimestamp() + "Grabbing events from " + lineAddress + "...",
    lineWebsite = requests.get(lineAddress, timeout=15)
    line_html = lineWebsite.text
    try:
        if lineWebsite.status_code == 200:
            body = ""
            split = line_html.split('<ul class="commentaries')  # [0]:nonsense [1]:events
            events = split[1].split('<li data-event-type="')
            events = events[1:]
            events = events[::-1]

            L = 0
            R = 0
            updatescores = True

            # goal.com's full commentary tagged as "action" - ignore these
            # will only report goals (+ penalties, own goals), yellows, reds, subs - not sure what else goal.com reports
            supportedEvents = ['goal', 'penalty-goal', 'own-goal', 'missed-penalty', 'yellow-card', 'red-card',
                               'yellow-red', 'substitution']
            for text in events:
                tag = re.findall('(.*?)"', text, re.DOTALL)[0]
                if tag.lower() in supportedEvents:
                    time = re.findall('<div class="time">\n?(.*?)<', text, re.DOTALL)[0]
                    time = time.strip()
                    info = "**" + time + "** "
                    event = re.findall('<div class="text">\n?(.*?)<', text, re.DOTALL)[0]
                    if event[-1] == ' ':
                        event = event[:-1]
                    if tag.lower() == 'goal' or tag.lower() == 'penalty-goal' or tag.lower() == 'own-goal':
                        if tag.lower() == 'goal':
                            event = event[:4] + ' ' + event[4:]
                            info += '[](/goal) **' + event + '**'
                        elif tag.lower() == 'penalty-goal':
                            event = event[:12] + ' ' + event[12:]
                            info += '[](/goal) **' + event + '**'
                        else:
                            event = event[:8] + ' ' + event[8:]
                            info += '[](/goal) **' + event + '**'
                        if find_scores_side(int(time.split("'")[0]), left, right) == 'left':
                            L += 1
                        elif find_scores_side(int(time.split("'")[0]), left, right) == 'right':
                            R += 1
                        else:
                            updatescores = False
                        if updatescores:
                            info += ' **' + str(L) + '-' + str(R) + '**'
                    if tag.lower() == 'missed-penalty':
                        event = event[:14] + ' ' + event[14:]
                        info += '[](/own-goal) **' + event + '**'
                    if tag.lower() == 'yellow-card':
                        event = event[:11] + ' ' + event[11:]
                        info += '[](/yellow) ' + event
                    if tag.lower() == 'red-card':
                        event = event[:8] + ' ' + event[8:]
                        info += '[](/red) ' + event
                    if tag.lower() == 'yellow-red':
                        event = event[:10] + ' ' + event[10:]
                        info += '[](/second-yellow) ' + event
                    if tag.lower() == 'substitution':
                        info += '[](/sub) Substitution: [](/down)' + \
                                re.findall('"sub-out">(.*?)<', text, re.DOTALL)[0]
                        info += ' [](/up)' + re.findall('"sub-in">(.*?)<', text, re.DOTALL)[0]
                    body += info + '\n\n'

                    #		print "complete."
            return body

        else:
            #		print "failed."
            return ""
    except:
        #		print "edit failed"
        #		logger.exception('[EDIT ERROR:]')
        return ""
'''


def find_streams(team1, team2):
    text = '**Got a stream for {} vs {}? Post it here!**\n\n'.format(team1, team2)
    text += "Check out /r/soccerstreams for more.\n\n___________________________________________________________"
    return text


def get_times(ko):
    hour = ko[0:ko.index(':')]
    minute = ko[ko.index(':') + 1:ko.index(':') + 3]
    ampm = ko[ko.index(' ') + 1:]
    hour_i = int(hour)
    min_i = int(minute)

    if (ampm == 'PM') and (hour_i != 12):
        hour_i += 12
    if (ampm == 'AM') and (hour_i == 12):
        hour_i = 0

    now_ = datetime.datetime.now()
    return hour_i, min_i, now_


# attempt submission to subreddit
def submit_thread(sub__, title):
    try:
        thread = r.submit(sub__, title, text='Updates soon', send_replies=False)
        return True, thread
    except:
        print '{}Submission error for "{}" in /r/{}'.format(get_timestamp(), title, sub__)
        logger.exception("[SUBMIT ERROR:]")
        return False, ''


# create a new thread using provided teams      
def create_new_thread(team1, team2, reqr, sub):
    site = find_goal_site(team1, team2)
    t1, t2, team1start, team1sub, team2start, team2sub, venue, ref, ko, status = get_gdc_info(site)
    if site != 'no match':

        botstat, statmsg = get_bot_status()
        # don't make a post if there's some fatal error
        if botstat == 'red':
            print get_timestamp() + "Denied " + t1 + " vs " + t2 + " request for - status set to red"
            logger.info("Denied %s vs %s request - status set to red", t1, t2)
            return 8, ''

        # don't post to a subreddit if it's blacklisted
        usrwhitelist = {"redravens"}

        # don't post if user is blacklisted

        # don't create a thread if the bot already made it or if user already has an active thread
        for d in activeThreads:
            matchid_at, t1_at, t2_at, id_at, reqr_at, sub_at = d
            if t1 == t1_at and sub == sub_at:
                print '{}Denied {} vs {} request for {} - thread already exists'.format(get_timestamp(), t1, t2, sub)
                logger.info("Denied %s vs %s request for %s - thread already exists", t1, t2, sub)
                return 4, id_at
            if reqr == reqr_at and reqr not in usrwhitelist:
                print get_timestamp() + "Denied post request from " + reqr + " - has an active thread request"
                logger.info("Denied post request from %s - has an active thread request", reqr)
                return 7, ''

        # don't create a thread if the match is done (probably found the wrong match)
        if status == 'FT' or status == 'PEN' or status == 'AET':
            print get_timestamp() + "Denied " + t1 + " vs " + t2 + " request - match appears to be finished"
            logger.info("Denied %s vs %s request - match appears to be finished", t1, t2)
            return 3, ''

        vidcomment = find_streams(team1, team2)
        title = 'Match Thread: {} vs {} [kickoff {} ET]'.format(t1, t2, kickoff1)
        result, thread = submit_thread(sub, title)

        # if subreddit was invalid, notify
        if not result:
            return 5, ''
        vidlink = thread.add_comment(vidcomment)
        # thread.set_suggested_sort(u'new')
        short = thread.short_link
        id_ = short[15:].encode("utf8")

        if status == 'v':
            status = "0'"

        body = '**' + status + ': ' + t1 + ' vs ' + t2 + '**\n\n--------\n\n'

        body += '[](/net) **Venue:** ' + venue + '\n\n' + '[](/whistle) **Referee:** ' + ref + \
                '\n\n--------\n\n'
        body += typeOfMatch
        body += availableOn
        body += '[](/video) **STREAMS**: '
        body += '[Video streams](' + vidlink.permalink + ')\n\n'
        body += '\n\n--------\n\n'
        body += '[](/notes)'
        body = write_lineups(body, t1, t2, team1start, team1sub, team2start, team2sub)

        body += '\n\n------------\n\n[](/clock) **MATCH EVENTS** | *via goal.com*\n\n'

        if botstat != 'green':
            body += '*' + statmsg + '*\n\n'

        thread.edit(body)
        sleep(10)
        data = site, t1, t2, id_, reqr, sub
        activeThreads.append(data)
        save_data()
        print '{}Active threads: {} - added {} vs {} (/r/{})'.format(get_timestamp(), len(activeThreads),
                                                                     t1, t2, sub)
        logger.info("Active threads: %i - added %s vs %s (/r/%s)", len(activeThreads), t1, t2, sub)
        return 0, id_
    else:
        print get_timestamp() + "Could not find match info for " + t1 + " vs " + t2
        logger.info("Could not find match info for %s vs %s", team1, team2)
        return 1, ''


# delete a thread (on admin request)
def delete_thread(id_):
    try:
        thread = r.get_submission(submission_id=id_)
        for data in activeThreads:
            match_id, team1, team2, thread_id, reqr, sub = data
            if thread_id == id_:
                thread.delete()
                activeThreads.remove(data)
                logger.info("Active threads: %i - removed %s vs %s (/r/%s)", len(activeThreads), team1, team2, sub)
                print '{}Active threads: {} - removed {} vs {} (/r/{})'.format(get_timestamp(),
                                                                                len(activeThreads), team1,
                                                                                team2, sub)
                save_data()
                return '{} vs {}'.format(team1, team2)
        return ''
    except Exception:
        return ''


# remove incorrectly made thread if requester asks within 5 minutes of creation
def remove_wrong_thread(id_, req):
    try:
        thread = r.get_submission(submission_id=id_)
        dif = datetime.datetime.utcnow() - datetime.datetime.utcfromtimestamp(thread.created_utc)
        for data in activeThreads:
            match_id, team1, team2, thread_id, reqr, sub = data
            if thread_id == id_:
                if reqr != req:
                    return 'req'
                if dif.days != 0 or dif.seconds > 300:
                    return 'time'
                thread.delete()
                activeThreads.remove(data)
                logger.info("Active threads: %i - removed %s vs %s (/r/%s)", len(activeThreads), team1, team2, sub)
                print '{}Active threads: {} - removed {} vs {} (/r/{})'.format(get_timestamp(), len(activeThreads),
                                                                               team1, team2, sub)
                save_data()
                return '{} vs {}'.format(team1, team2)
        return 'thread'

    except Exception:
        return 'thread'


# default attempt to find teams: split input in half, left vs right     
def first_try_teams(msg):
    t = msg.split()
    spl = len(t) / 2
    t1 = t[0:spl]
    t2 = t[spl + 1:]
    t1s = ''
    t2s = ''
    for word in t1:
        t1s += word + ' '
    for word in t2:
        t2s += word + ' '
    return [t1s, t2s]


# check for new mail, create new threads if needed
def check_and_create():
    delims = [' x ', ' - ', ' v ', ' vs ']
    subdel = ' for '
    admin = 'RedRavens'
    for msg in r.get_unread(unset_has_mail=True, update_user=True, limit=None):
        sub = 'ussoccer'
        msg.mark_as_read()
        if 'poke' in msg.subject.lower():
            msg.reply("I'm alive!")
        if 'match thread r3d' in msg.subject.lower():
            subreq_ = msg.body.split(subdel, 2)
            if subreq_[0] != msg.body:
                sub = subreq_[1].split('/')[-1]
                sub = sub.lower()
                sub = sub.strip()
            teams_ = first_try_teams(subreq_[0])
            for delim in delims:
                attempt_ = subreq_[0].split(delim, 2)
                if attempt_[0] != subreq_[0]:
                    teams_ = attempt_
            thread_status_, thread_id = create_new_thread(teams_[0], teams_[1], msg.author.name, sub)
            if thread_status_ == 0:  # thread created successfully
                msg.reply("[Here](http://www.reddit.com/r/" + sub + "/comments/" + thread_id +
                          ") is a link to the thread you've requested. Thanks for using this bot!"
                          "\n\n-------------------------\n\n*Did I create a thread for the wrong match? "
                          "[Click here and press send](http://www.reddit.com/message/compose/?to=ussoccer_bot"
                          "&subject=delete&message=" + thread_id + ") to delete the thread (note: this will only"
                                                                   " work within five minutes of the thread's"
                                                                   " creation). This probably means that I can't"
                                                                   " find the right match - sorry!*")
                '''
                account_sid = 'AC2799d2a62369c35a8461b5d6e27a19ac'
                authtoken = 'bd7274f70c7d3d8c92e59d26b3905ea1'
                twiliocli = TwilioRestClient(account_sid, authtoken)
                mytwilionumber = '+17693012706'
                my = '+14044346571'
                twiliocli.messages.create(body='Match Thread created via PM',
                                          from_=mytwilionumber, to=my)
                '''
            if thread_status_ == 1:  # not found
                msg.reply("Sorry, I couldn't find info for that match. In the future "
                          "I'll account for more matches around the world.")
            if thread_status_ == 2:  # before kickoff
                msg.reply("Please wait until kickoff to send me a thread request, "
                          "just in case someone does end up making one themselves. Thanks!")
            if thread_status_ == 3:  # after kickoff - probably found the wrong match
                msg.reply("Sorry, I couldn't find info for that match. In the future I'll account "
                          "for more matches around the world.")
            if thread_status_ == 4:  # thread already exists
                msg.reply("There is already a [match thread](http://www.reddit.com/r/" + sub +
                          "/comments/" + thread_id + ") for that game. Join the discussion there!")
            if thread_status_ == 5:  # invalid subreddit
                msg.reply("Sorry, I couldn't post to /r/" + sub + ". It may not exist, or "
                                                                  "I may have hit a posting limit.")
            if thread_status_ == 6:  # sub blacklisted
                msg.reply("Sorry, I cannot post to /r/" + sub + ". Please contact the subreddit "
                                                                "mods if you'd like more info.")
            if thread_status_ == 7:  # thread limit
                msg.reply("Sorry, you can only have one active thread request at a time.")
            if thread_status_ == 8:  # status set to red
                msg.reply("Sorry, the bot is currently unable to post threads. Check with /u/RedRavens"
                          " for more info; this should hopefully be resolved soon.")

        if msg.subject.lower() == 'delete':
            if msg.author.name == admin:
                name = delete_thread(msg.body)
                if name != '':
                    msg.reply("Deleted " + name)
                else:
                    msg.reply("Thread not found")
            else:
                name = remove_wrong_thread(msg.body, msg.author.name)
                if name == 'thread':
                    msg.reply("Thread not found - please double-check thread ID")
                elif name == 'time':
                    msg.reply("This thread is more than five minutes old - "
                              "thread deletion from now is an admin feature only. You "
                              "can message /u/RedRavens if you'd still like the thread to be deleted.")
                elif name == 'req':
                    msg.reply("Username not recognised. Only the thread requester and "
                              "bot admin have access to this feature.")
                else:
                    msg.reply("Deleted " + name)


def get_extra_info(match_id):
    lineaddress = "http://www.goal.com/en-us/match/" + match_id
    req = urllib2.Request(lineaddress, headers=hdr)
    linewebsite = urllib2.urlopen(req)
    line_html_enc = linewebsite.read()
    line_html = line_html_enc.decode("utf8")
    info = re.findall('<div class="away-score">.*?<p>(.*?)<', line_html, re.DOTALL)[0]
    return info


# update score, scorers
def update_score(match_id, t1, t2):
    line_address = "http://www.goal.com/en-us/match/" + match_id
    req = urllib2.Request(line_address, headers=hdr)
    line_website = urllib2.urlopen(req)
    line_html_enc = line_website.read()
    line_html = line_html_enc.decode("utf8")
    leftscore = re.findall('<div class="home-score">(.*?)<', line_html, re.DOTALL)[0]
    rightscore = re.findall('<div class="away-score">(.*?)<', line_html, re.DOTALL)[0]
    info = get_extra_info(match_id)
    status = get_status(match_id)
    # goal_updating = True
    if status == 'v':
        status = "0'"
        # goal_updating = False

    split1 = line_html.split('<div class="home"')  # [0]:nonsense [1]:scorers
    split2 = split1[1].split('<div class="away"')  # [0]:home scorers [1]:away scorers + nonsense
    split3 = split2[1].split('<div class="module')  # [0]:away scorers [1]:nonsense

    leftscorers = re.findall('<a href="/en-us/people/.*?>(.*?)<', split2[0], re.DOTALL)
    rightscorers = re.findall('<a href="/en-us/people/.*?>(.*?)<', split3[0], re.DOTALL)

    text = '**{}: {} {}-{} {}**\n\n'.format(status, t1, leftscore, rightscore, t2)
    # if not goalUpdating:
    #                text += '*goal.com might not be providing match updates for this game.*\n\n'

    if info != '':
        text += '***' + info + '***\n\n'

    left = ''
    if leftscorers:
        left += "*" + t1 + " scorers: "
        for scorer in leftscorers:
            scorer = scorer.replace('&nbsp;', ' ')
            left += scorer + ", "
        left = left[0:-2] + "*"

    right = ''
    if rightscorers:
        right += "*" + t2 + " scorers: "
        for scorer in rightscorers:
            scorer = scorer.replace('&nbsp;', ' ')
            right += scorer + ", "
        right = right[0:-2] + "*"

    text += left + '\n\n' + right

    return text, left, right


# update all current threads                    
def update_threads():
    to_remove = []
    for data in activeThreads:
        finished = False
        index = activeThreads.index(data)
        match_id, team1, team2, thread_id, reqr, sub = data
        thread = r.get_submission(submission_id=thread_id)
        body = thread.selftext
        venue_index = body.index('**Venue:**')

        # detect if finished
        if get_status(match_id) == 'FT' or get_status(match_id) == 'AET':
            finished = True
        elif get_status(match_id) == 'PEN':
            info = get_extra_info(match_id)
            if 'won' in info or 'win' in info:
                finished = True

        # update lineups (sometimes goal.com changes/updates them)
        team1_start, team1_sub, team2_start, team2_sub = get_lineups(match_id)
        lineup_index = body.index('**LINE-UPS**')
        body_then = body[venue_index:lineup_index]
        newbody = write_lineups(body_then, team1, team2, team1_start, team1_sub, team2_start, team2_sub)
        newbody += '\n\n------------\n\n[](/net) **MATCH EVENTS** | *via goal.com*\n\n'

        botstat, statmsg = get_bot_status()
        if botstat != 'green':
            newbody += '*Note: ' + statmsg + '*\n\n'

        # update scorelines
        score, left, right = update_score(match_id, team1, team2)
        newbody = score + '\n\n--------\n\n' + newbody

        events = grab_events(match_id, left, right)
        newbody += '\n\n' + events

        # save data
        if newbody != body:
            logger.info("Making edit to %s vs %s (/r/%s)", team1, team2, sub)
            print '{}Making edit to {} vs {} (/r/{})'.format(get_timestamp(), team1, team2, sub)
            thread.edit(newbody)
            save_data()
        newdata = match_id, team1, team2, thread_id, reqr, sub
        activeThreads[index] = newdata

        if finished:
            to_remove.append(newdata)

    for getRid in to_remove:
        activeThreads.remove(getRid)
        logger.info("Active threads: %i - removed %s vs %s (/r/%s)", len(activeThreads),
                    getRid[1], getRid[2], getRid[5])
        print '{} Active threads: {} - removed {} vs {} (/r/{}'.format(get_timestamp(),
                                                                       len(activeThreads), getRid[1],
                                                                       getRid[2], getRid[5])
        save_data()
        sys.exit()


if __name__ == '__main__':
    logger = logging.getLogger('a')
    logger.setLevel(logging.ERROR)
    logfilename = 'log.log'
    handler = logging.handlers.RotatingFileHandler(logfilename, maxBytes=50000, backupCount=5)
    handler.setLevel(logging.ERROR)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.info("[STARTUP]")
    logging.disable(logging.DEBUG)
    print "{}[STARTUP]".format(get_timestamp())

    # every minute, check mail, create new threads, update all current threads
    if 's/A' not in os.getcwd():
        mntpath = '/media/usb/Server/mnt.txt'
        wntpath = '/media/usb/Server/wnt.txt'
        ussoccerpath = '/media/usb/Server/MatchThreader/.ussoccer.txt'
    else:
        mntpath = '/Users/Alex/Documents/mnt.txt'
        wntpath = '/Users/Alex/Documents/wnt.txt'
        ussoccerpath = '/Users/Alex/Documents/Python/MatchThreader/.ussoccer.txt'

    with open(mntpath, 'r') as files:
        opp, place, date, network, kickoff1 = files.read().split('?')

    with open(wntpath, 'r') as files:
        w_opp, w_place, w_date, w_network, w_kickoff1 = files.read().split('?')

    if str(datetime.datetime.now().day) in w_date and w_date[:w_date.index('.')] in \
            datetime.datetime.now().strftime("%B"):
        opp = w_opp
        place = w_place
        date = w_date
        network = w_network
        kickoff1 = w_kickoff1

    del w_opp, w_place, w_date, w_network, w_kickoff1

    subject = 'United States vs {}'.format(opp)

    try:
        if 'PM' in kickoff1 and '12' not in kickoff1:
            kickoff2 = int(kickoff1[:kickoff1.index(':')]) + 12
        else:
            kickoff2 = int(kickoff1[:kickoff1.index(':')])
    except ValueError:
        kickoff2 = 1

    typeOfMatch = '**[](/fifa) World Cup Qualifying** \n\n'
    avail = '{}, UniMas, Univision'.format(network)
    subjectText = '{} for /r/ussoccer'.format(subject)
    availableOn = '[](/announcement) **Available on**: {}\n\n'.format(avail)

    # browser header (to avoid 405 error with goal.com, streaming sites)
    hdr = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.11 '
                         '(KHTML, like Gecko) Chrome/23.0.1271.64 Safari/537.11',
           'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
           'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.3',
           'Accept-Encoding': 'none',
           'Accept-Language': 'en-US,en;q=0.8',
           'Connection': 'keep-alive'}

    activeThreads = []
    notify = False

    # login time!
    user_agent = "Match Thread v2.0 created by /u/RedRavens, using OAuth and /u/ussoccer_b0t"
    with open(ussoccerpath) as filep:
        if 's/A' in ussoccerpath:
            key, refresh, access = filep.read().split('\n')
        else:
            key, refresh, access, __ = filep.read().split('\n')

    r = praw.Reddit(user_agent, oauth_client_id='_3vsO2wedhIMtw', oauth_client_secret=key,
                    oauth_redirect_uri='http://127.0.0.1:65010/authorize_callback'
                    )

    access_information = {'access_token': access,
                          'refresh_token': refresh,
                          'scope': {'account creddits edit flair history identity livemanage modconfig '
                                    'modcontributors modflair modlog modothers modposts modself modwiki '
                                    'mysubreddits privatemessages read '
                                    'report save submit subscribe vote wikiedit wikiread'}
                          }
    access = r.refresh_access_information(access_information['refresh_token'])
    r.set_access_credentials(**access)

    read_data()

    running = True
    z = 0
    while running:
        try:
            check_and_create()
            update_threads()
            now = datetime.datetime.now()

            if now.hour == (kickoff2 - 1) and z == 0:
                z = 1
                html = requests.get(
                    'http://www.goal.com/en-us/match/{}'.format(find_goal_site("United States", opp))).text
                if "United States" in html and opp in html:
                    delims_ = [' x ', ' - ', ' v ', ' vs ']
                    subdel_ = ' for '

                    subreq = subjectText.split(subdel_, 2)
                    if subreq[0] != subjectText:
                        sub_ = subreq[1].split('/')[-1]
                        sub_ = sub_.lower()
                        sub_ = sub_.strip()
                    teams = first_try_teams(subreq[0])
                    for delim_ in delims_:
                        attempt = subreq[0].split(delim_, 2)
                        if attempt[0] != subreq[0]:
                            teams = attempt
                    thread_status, thread_id_ = create_new_thread(teams[0], teams[1], "RedRavens", sub_)
                    if thread_status == 0:  # thread created successfully
                        r.send_message('RedRavens', 'Match Thread',
                                       "[Here](http://www.reddit.com/r/" + sub_ + "/comments/" + thread_id_ +
                                       ") is a link to the thread you've requested. Thanks for using this bot!"
                                       "\n\n-------------------------\n\n*Did I create a thread for the wrong match? "
                                       "[Click here and press send](http://www.reddit.com/message/compose/?to="
                                       "ussoccer_bot"
                                       "&subject=delete&message=" + thread_id_ + ") to delete the thread (note: this"
                                                                                 " will only"
                                                                                 " work within five minutes of the "
                                                                                 "thread's"
                                                                                 " creation). This probably means that"
                                                                                 " I can't"
                                                                                 " find the right match - sorry!*")
                        #
                    if thread_status == 1:  # not found
                        r.send_message('RedRavens', 'Match Thread',
                                       "Sorry, I couldn't find info for that match. In the future "
                                       "I'll account for more matches around the world.")
                    if thread_status == 2:  # before kickoff
                        r.send_message('RedRavens', 'Match Thread',
                                       "Please wait until kickoff to send me a thread request, "
                                       "just in case someone does end up making one themselves. Thanks!")
                    if thread_status == 3:  # after kickoff - probably found the wrong match
                        r.send_message('RedRavens', 'Match Thread',
                                       "Sorry, I couldn't find info for that match. In the future I'll account "
                                       "for more matches around the world.")
                    if thread_status == 4:  # thread already exists
                        r.send_message('RedRavens', 'Match Thread',
                                       "There is already a [match thread](http://www.reddit.com/r/{}/comments/{} for"
                                       " that game. Join the discussion there!".format(sub_, thread_id_))
                    if thread_status == 5:  # invalid subreddit
                        r.send_message('RedRavens', 'Match Thread',
                                       "Sorry, I couldn't post to /r/{}. It may not exist, or "
                                       "I may have hit a posting limit.".format(sub_)
                                       )
                    if thread_status == 6:  # sub blacklisted
                        r.send_message('RedRavens', 'Match Thread',
                                       "Sorry, I cannot post to /r/{}. Please contact the subreddit "
                                       "mods if you'd like more info.".format(sub_))
                    if thread_status == 7:  # thread limit
                        r.send_message('RedRavens', 'Match Thread',
                                       "Sorry, you can only have one active thread request at a time.")
                    if thread_status == 8:  # status set to red
                        r.send_message('RedRavens', "Match Thread", "Sorry, the bot is currently unable to"
                                                                    " post threads."
                                                                    " Check with /u/RedRavens"
                                                                    " for more info; "
                                                                    "this should hopefully be resolved soon.")
                else:
                    matchtype = 'International Friendly'
                    body = '**{}**\n\n---\n\n' \
                           '**Opponent:** {}\n\n---\n\n**Available on:** {}\n\n---\n\n**Lineup:** TBD'.format(
                        matchtype, opp, network)
                    title_text = 'Match Thread: WNT vs {} [kickoff {} ET]'.format(opp, kickoff1)
                    r.submit('ussoccer', title_text, text=body, send_replies=False)
                    account_sid_ = 'AC2799d2a62369c35a8461b5d6e27a19ac'
                    authtoken_ = 'bd7274f70c7d3d8c92e59d26b3905ea1'
                    twiliocli_ = TwilioRestClient(account_sid_, authtoken_)
                    mytwilionumber_ = '+17693012706'
                    my_ = '+14044346571'
                    message = twiliocli_.messages.create(body='Match Thread created'
                                                              ' but goal.com is not providing updates',
                                                         from_=mytwilionumber_, to=my_)

            sleep(60)

        except praw.errors.OAuthInvalidToken:
            print get_timestamp() + "Token expired, refreshing"
            logger.exception("[EXPIRED TOKEN:]")
        except praw.errors.APIException:
            print get_timestamp() + "API error, check log file"
            logger.exception("[API ERROR:]")
            sleep(60)
        except Exception as excep:
            print get_timestamp() + "{}, check log file. {}".format(excep, traceback.format_exc())
            logger.exception('ERROR: {}; {}'.format(excep, traceback.format_exc()))
            sleep(60)
