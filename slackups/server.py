import asyncio
import logging

import hangups
import hangups.auth
from hangups.ui.utils import get_conv_name


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

        self.slack._conv_list = self._conv_list
        self.slack._user_list = self._user_list

        self._conv_list.on_event.add_observer(self._on_hangups_event)
        logger.info('Hangups connected.')

        asyncio.async(self.slack.run())


    @asyncio.coroutine
    def _on_hangups_event(self, conv_event, retry=0):
        """Called when a hangups conversation event occurs."""
        try:
            logger.info("Hangups Event: "+conv_event.__class__.__name__)
            if isinstance(conv_event, hangups.ChatMessageEvent):
                conv = self._conv_list.get(conv_event.conversation_id)
                user = conv.get_user(conv_event.user_id)
                sender = util.get_nick(user)
                hostmask = util.get_hostmask(user)
                channel = util.conversation_to_channel(conv)
                message = conv_event.text
                print((hostmask+' -> '+channel+' : '+conv_event.text).encode('utf-8'))
                yield from self.slack.hangoutsMessage(conv, user, message)
            elif isinstance(conv_event, hangups.RenameEvent):
                conv = self._conv_list.get(conv_event.conversation_id)
                yield from self.slack.onHangoutsRename(conv, conv_event.old_name, conv_event.new_name)
            elif isinstance(conv_event, hangups.MembershipChangeEvent):
                conv = self._conv_list.get(conv_event.conversation_id)
                users = [conv.get_user(uid) for uid in conv_event.participant_ids]
                if conv_event.type == MEMBERSHIP_CHANGE_TYPE_JOIN:
                    yield from self.slack.onHangoutsJoin(conv, users)
                elif conv_event.type == MEMBERSHIP_CHANGE_TYPE_LEAVE:
                    yield from self.slack.onHangoutsLeave(conv, users)
                else:
                    logger.warning("Unknown membership change type: "+str(conv_event.type))

        except:
            logger.exception("Error handling hangouts event!")
            if retry < 5:
                yield from asyncio.sleep(retry+0.1)
                logger.info("RETRYING")
                yield from self._on_hangups_event(conv_event, retry+1)
            else:
                logger.critical("##########GAVE UP RETRYING############")


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


