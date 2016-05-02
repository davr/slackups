from . import util
import asyncio
import logging
import os.path
import os
import urllib.request
import hashlib
import json
import appdirs
from time import time

from slackclient import SlackClient

logger = logging.getLogger(__name__)
TICK = 0.01

class SlackGateway:

    def __init__(self):
        self.IMGDIR = "/home/hangups/icons"
        self.IMGURL = "http://davr.org/slackicons"
        self.SLACK_TOKEN_URL = 'https://api.slack.com/docs/oauth-test-tokens#test_token_generator'

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
        while True:
            for event in self.client.rtm_read():
                et = event['type']
                logger.info(json.dumps(event).encode('utf-8'))
                if et == 'message':
                    # normal messages have no subtype
                    if not 'subtype' in event:
                        # reply_to is a response from server telling us they got the msg, ignore it
                        if not 'reply_to' in event:
                           logger.info("Send msg")

            yield from asyncio.sleep(TICK)

    def convHash(self, conv):
        return hashlib.sha1(conv.id_.encode()).hexdigest()

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

        self.addGroup({'id':channelID, 'purpose':{'value':purpose}})

        return channelID

    @asyncio.coroutine
    def hangoutsMessage(self, conv, user, message):
        channelID = yield from self.convToChan(conv)

        if channelID is None:
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

        self.client.api_call('chat.postMessage',
                channel=channelID,
                text=message,
                as_user=False,
                username=nick,
                icon_url=imgurl
                )


    def privmsg(self, hostmask, channel, message):
        pass


