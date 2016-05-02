from . import util
import asyncio
import logging
import os.path
import urllib.request
import hashlib
import json
from time import time

from slackclient import SlackClient

logger = logging.getLogger(__name__)

class SlackGateway:

    def __init__(self):
        self.IMGDIR = "/home/hangups/icons"
        self.IMGURL = "http://davr.org/slackicons"

        self.loadConfig()

    def loadConfig(self):
        config = os.path.expanduser("~/.slangouts/config.json")
        if not os.path.isfile(config):
            logging.critical("ERROR config file missing")
            return

        with fp = open(config):
            data = json.load(fp)

        self.token = data['slackApiToken']

    def connect(self):
        self.client = SlackClient(self.token)
        if self.client.rtm_connect():
            logger.info("Connected to Slack!")
        else:
            logger.critical("ERROR CONNCTING TO SLACK check token?")

    @asyncio.coroutine
    def run(self):
        logger.info("Starting slack event loop")
        yield from asyncio.sleep(0.1)
        for channel in self.client.server.channels:
            n = str(channel.name)
            i = str(channel.id)
            logger.info("Slack Channel: "+n+" ["+i+"]")
        yield from asyncio.sleep(0.1)
        while True:
            for event in self.client.rtm_read():
                et = event['type']
                if et == 'message':
                    logger.info(json.dumps(event).encode('utf-8'))

                    # normal messages have no subtype
                    if not 'subtype' in event:
                        # reply_to is a response from server telling us they got the msg, ignore it
                        if not 'reply_to' in event:
                           logger.info("Send msg")

            yield from asyncio.sleep(0.1)

    def hangoutsMessage(self, channel, user, message):
        nick = util.get_nick(user)
        schannel = self.client.server.channels.find(channel.lower())
        if schannel:
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
                    channel=schannel.id,
                    text=message,
                    as_user=False,
                    username=nick,
                    icon_url=imgurl
                    )
        else:
            logger.warning('Cannot find channel '+channel)


    def privmsg(self, hostmask, channel, message):
        pass


