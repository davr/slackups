from . import util
from . import emoji
import asyncio
import logging
import os.path
import os
import urllib.request
import hashlib
import json
import appdirs
import hangups
from time import time

from slackclient import SlackClient

logger = logging.getLogger(__name__)
TICK = 0.01

class SlackGateway:

    def __init__(self):
        self.IMGDIR = "/home/hangups/icons"
        self.IMGURL = "http://davr.org/slackicons"
        self.SLACK_TOKEN_URL = 'https://api.slack.com/docs/oauth-test-tokens#test_token_generator'
        self.sent_messages = {}

        self.loadConfig()

    def loadConfig(self):
        dirs = appdirs.AppDirs('slackups', 'slackups')
        config = os.path.join(dirs.user_cache_dir, 'config.json')

        try:
            with open(config,'r') as fp:
                data = json.load(fp)

            self.token = data['slackApiToken']

        except:
            print("To log in to slack, go to the following URL to generate a token:")
            print(self.SLACK_TOKEN_URL)
            self.token = input('\nSlack Test Token: ')
            data = {'slackApiToken': self.token}
            os.makedirs(dirs.user_cache_dir, exist_ok=True)
            with open(config, 'w') as fp:
                json.dump(data, fp)


    def connect(self):
        self.client = SlackClient(self.token)
        if self.client.rtm_connect():
            logger.info("Connected to Slack!")
        else:
            logger.critical("ERROR CONNCTING TO SLACK check token?")

    def addGroup(self, group):
        self.groups[group['id']] = group
        purpose = group['purpose']['value']
        if purpose[0:17] == 'Hangouts Bridge: ':
            hangoutid = purpose[17:]
            self.grouphash[hangoutid] = group['id']
            logger.info("Group "+group['id']+" to hash "+hangoutid)

    @asyncio.coroutine
    def run(self):
        logger.info("Starting slack event loop")
        yield from asyncio.sleep(TICK)
        logger.info("Requesting slack groups")
        res = self.client.api_call('groups.list', exclude_archived=1)
        self.groups = dict()
        self.grouphash = dict()
        if 'ok' in res and res['ok']:
            for group in res['groups']:
                self.addGroup(group)
        else:
            logger.critical("ERROR LISTING SLACK GROUPS check token?")
            logger.critical(json.dumps(res).encode("utf-8"))

        yield from asyncio.sleep(TICK)

        logger.info("Setting bot away")
        res=self.client.api_call('users.setPresence', presence='away')
        logger.info(json.dumps(res).encode('utf-8'))
        yield from asyncio.sleep(TICK)


        while True:
            for event in self.client.rtm_read():
                et = event['type']
                logger.info(json.dumps(event).encode('utf-8'))
                if et == 'message':
                    # normal messages have no subtype
                    if not 'subtype' in event:
                        # reply_to is a response from server telling us they got the msg, ignore it
                        if not 'reply_to' in event:
                           self.slackMessage(event['channel'], event['user'], event['text'])
                           if 'attachments' in event:
                               for attachment in event['attachments']:
                                   self.slackMessage(event['channel'], event['user'], attachment['fallback'])

            yield from asyncio.sleep(TICK)

    def slackMessage(self, channel, user, text):
        if user != "U03NV5HLH":
            logger.info("Ignoring unk dude")
            return

        conv = self.chanToConv(channel)
        logger.info(text.encode('utf-8'))
        msg = emoji.shortcode_to_emoji(text)
        logger.info(msg.encode('utf-8'))
        self.sent_messages[channel+msg] = True
        segments = hangups.ChatMessageSegment.from_str(msg)
        asyncio.async(conv.send_message(segments))

    def convHash(self, conv):
        return hashlib.sha1(conv.id_.encode()).hexdigest()

    def chanToConv(self, channel):
        if channel not in self.groups:
            logger.warning("Unknown channel "+channel)
        
        group = self.groups[channel]
        purpose = group['purpose']['value']
        if purpose[0:17] == 'Hangouts Bridge: ':
            hangoutid = purpose[17:]

        return {hashlib.sha1(conv.id_.encode()).hexdigest(): conv
                for conv in self._conv_list.get_all()}[hangoutid]

    @asyncio.coroutine
    def convToChan(self, conv):
        chash = self.convHash(conv)
        if chash in self.grouphash:
            return self.grouphash[chash]

        cname = util.conversation_to_channel(conv)

        res = self.client.api_call('groups.create', name=cname)
        yield from asyncio.sleep(TICK)

        if not 'ok' in res or not res['ok']:
            logger.critical("ERROR CREATING GROUP")
            logger.critical(json.dumps(res).encode("utf-8"))
            return None

        channelID = res['group']['id']

        res = self.client.api_call('groups.setPurpose', channel=channelID, purpose="Hangouts Bridge: "+chash)
        yield from asyncio.sleep(TICK)

        if not 'ok' in res or not res['ok']:
            logger.critical("ERROR SETTING PURPOSE")
            logger.critical(json.dumps(res).encode("utf-8"))

        purpose = res['purpose']

        res = self.client.api_call('groups.setTopic', channel=channelID, topic=util.get_topic(conv))
        yield from asyncio.sleep(TICK)

        if not 'ok' in res or not res['ok']:
            logger.critical("ERROR SETTING TOPIC")
            logger.critical(json.dumps(res).encode("utf-8"))

        res = self.client.api_call('groups.invite', channel=channelID, user="U03NV5HLH")
        yield from asyncio.sleep(TICK)

        self.addGroup({'id':channelID, 'name':cname, 'topic':{'value':util.get_topic(conv)}, 'purpose':{'value':purpose}})

        return channelID

    @asyncio.coroutine
    def onHangoutsRename(self, conv, old_name, new_name):
        channelID = yield from self.convToChan(conv)
        if channelID is None:
            return

        group = self.groups[channelID]

        ctopic = util.get_topic(conv)
        cname = util.conversation_to_channel(conv)

        if group['name'] != cname:
            res = self.client.api_call('groups.rename', channel=channelID, name=cname)
            yield from asyncio.sleep(TICK)
            if 'ok' in res and res['ok']:
                group['name'] = res['channel']['name']

        if group['topic']['value'] != ctopic:
            res = self.client.api_call('groups.setTopic', channel=channelID, topic=ctopic)
            yield from asyncio.sleep(TICK)
            if 'ok' in res and res['ok']:
                group['topic']['value'] = res['topic']


    @asyncio.coroutine
    def onHangoutsJoin(self, conv, users):
        yield

    @asyncio.coroutine
    def onHangoutsLeave(self, conv, users):
        yield

    @asyncio.coroutine
    def hangoutsMessage(self, conv, user, message):
        channelID = yield from self.convToChan(conv)

        if channelID is None:
            return

        if (channelID+message) in self.sent_messages:
            del self.sent_messages[channelID+message]
            logger.warning("Ignoring self message")
            return

        if user is None:
            logger.warning("Missing user in hangoutsMessage?")
            return

        nick = util.get_nick(user)
        if user.photo_url is None:
            imgurl = self.IMGUR + "/default.jpg"
        else:
            img = hashlib.md5(user.photo_url.encode()).hexdigest()

            imgurl = self.IMGURL + "/" + img + ".jpg"

            imgfile = self.IMGDIR + "/" + img + ".jpg"
            if not os.path.isfile(imgfile):
                logger.info(("Downloading profile photo for "+nick).encode('utf-8'))
                logger.info("URL: "+user.photo_url)
                logger.info("Dest: "+imgfile)
                logger.info("Local URL: "+imgurl)
                urllib.request.urlretrieve("http:"+user.photo_url, imgfile)
                yield from asyncio.sleep(TICK)

        self.client.api_call('chat.postMessage',
                channel=channelID,
                text=message,
                as_user=False,
                username=nick,
                icon_url=imgurl
                )


    def privmsg(self, hostmask, channel, message):
        pass


