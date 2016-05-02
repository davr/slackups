import asyncio
import logging

import hangups
import hangups.auth

from . import util, slackgateway

logger = logging.getLogger(__name__)


class Server:

    def __init__(self, cookies=None, ascii_smileys=False):
        self.clients = {}
        self._hangups = hangups.Client(cookies)
        self._hangups.on_connect.add_observer(self._on_hangups_connect)
        self.ascii_smileys = True #ascii_smileys

    def run(self, host, port):
        self.loop = loop = asyncio.get_event_loop()

        logger.info('Connecting to slack')
        self.slack = slackgateway.SlackGateway()
        self.slack.connect()

        logger.info('Waiting for hangups to connect...')
        try:
            loop.run_until_complete(self._hangups.connect())
        finally:
            logger.info("Goodbye")
            loop.close()

    # Hangups Callbacks

    @asyncio.coroutine
    def _on_hangups_connect(self):
        """Called when hangups successfully auths with hangouts."""
        logger.info('Hangups connected...')
        self._user_list, self._conv_list = (
            yield from hangups.build_user_conversation_list(self._hangups)
        )

        for conv in self._conv_list.get_all():
            util.conversation_to_channel(conv)

        self._conv_list.on_event.add_observer(self._on_hangups_event)
        logger.info('Hangups connected.')

        task = asyncio.Task(self.slack.run())


    def _on_hangups_event(self, conv_event):
        """Called when a hangups conversation event occurs."""
        if isinstance(conv_event, hangups.ChatMessageEvent):
            conv = self._conv_list.get(conv_event.conversation_id)
            user = conv.get_user(conv_event.user_id)
            sender = util.get_nick(user)
            hostmask = util.get_hostmask(user)
            channel = util.conversation_to_channel(conv)
            message = conv_event.text
            print((hostmask+' -> '+channel+' : '+conv_event.text).encode('utf-8'))
            self.slack.hangoutsMessage(channel, user, message)

    # Client Callbacks

    def _on_client_connect(self, client_reader, client_writer):
        """Called when an IRC client connects."""
        client = ircgateway.IRCGateway(client_reader, client_writer)
        client._conv_list = self._conv_list
        client._user_list = self._user_list
        client._hangups = self._hangups
        client.connectionMade()

        task = asyncio.Task(self._handle_client(client))
        self.clients[task] = client
        logger.info("New Connection")
        task.add_done_callback(self._on_client_lost)

    def _on_client_lost(self, task):
        """Called when an IRC client disconnects."""
        self.clients[task].writer.close()
        del self.clients[task]
        logger.info("End Connection")


