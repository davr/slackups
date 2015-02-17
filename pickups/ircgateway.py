from . import irc, util
import asyncio
import logging
import hangups
import hangups.auth

class IRCGateway(irc.IRC):

    def __init__(self, reader, writer):
        super().__init__(reader,writer)
        self.sent_messages = []
        self.channels = {}

    def irc_NICK(self, prefix, params):
        print("Got a NICK from %s to %s!" % (prefix, params[0]))
        self.nickname = params[0]

    def irc_USER(self, prefix, params):
        print("Got USER '%s'" % params[0])
        self.username = params[0]

    def myhostmask(self):
        return util.get_hostmask(self._user_list._self_user)

    def joinself(self, channel):
        """Join myself to a channel"""
        self.join(self.myhostmask(), channel)
        self.channels[channel] = True

    def partself(self, channel):
        """Part myself from a channel"""
        self.part(self.myhostmask(), channel)
        del self.channels[channel]

    def irc_LIST(self, prefix, params):
        info = (
            (util.conversation_to_channel(conv), len(conv.users),
             util.get_topic(conv)) for conv in self._conv_list.get_all()
        )
        self.list_channels(info)

    def irc_PRIVMSG(self, prefix, params):
        channel = params[0]
        message = ' '.join(params[1:])
        conv = util.channel_to_conversation(channel, self._conv_list)
        self.sent_messages.append(message)
        segments = hangups.ChatMessageSegment.from_str(message)
        asyncio.async(conv.send_message(segments))

    def irc_JOIN(self, prefix, params):
        channels = params[0]
        channels = channels.split(',')
        for channel in channels:
            self.dojoin(channel)


    def dojoin(self, channel):
        """Do a full join process on a channel (join msg, topic, names list)"""
        print("Joining '"+channel+"'")
        conv = util.channel_to_conversation(channel, self._conv_list)
        # If a JOIN is successful, the user receives a JOIN message as
        # confirmation and is then sent the channel's topic (using
        # irc.RPL_TOPIC) and the list of users who are on the channel (using
        # irc.RPL_NAMREPLY), which MUST include the user joining.
#                    self.write(util.get_nick(self._user_list._self_user),
#                                 'JOIN', channel)
        self.joinself(channel)
        self.topic(self.nickname, channel, util.get_topic(conv))
        self.names(self.nickname, channel, 
                          (util.get_nick(user) for user in conv.users))

    def irc_PART(self, prefix, params):
        channels = params[0]
        channels = channels.split(',')
        for channel in channels:
            conv = util.channel_to_conversation(channel, self._conv_list)
            self.partself(channel)


    def irc_WHO(self, prefix, params):
        query = params[0]

        if query.startswith('#'):
            conv = util.channel_to_conversation(query,
                                                 self._conv_list)
            responses = [(
                util.get_name(user),
                util.get_hostmask(user),
                self.hostname,
                util.get_nick(user),
                'H',
                1,
                user.full_name
            ) for user in conv.users]
            self.who(self.nickname, query, responses)

    def irc_PING(self, prefix, params):
        self.pong(params)

    def irc_QUIT(self, prefix, params):
        self.close()


    def welcome(self):
        self.swrite(irc.RPL_WELCOME, ':Welcome to pickups!')
        self.swrite(irc.RPL_YOURHOST, ':Your host is cool')
        self.swrite(irc.RPL_CREATED, ':This server is cool')
        self.swrite(irc.RPL_MYINFO, 'hangups ircd-etc')
        self.swrite(irc.RPL_ISUPPORT, 'CHANTYPES=# EXCEPTS INVEX CHANMODES=eIbq,k,flj,CFLMPQScgimnprstz CHANLIMIT=#:120 PREFIX=(ov)@+ MAXLIST=bqeI:100 MODES=4 NETWORK=freenode KNOCK STATUSMSG=@+ CALLERID=g :are supported by this server')
        self.swrite(irc.RPL_ISUPPORT, 'CASEMAPPING=rfc1459 CHARSET=ascii NICKLEN=16 CHANNELLEN=50 TOPICLEN=390 ETRACE CPRIVMSG CNOTICE DEAF=D MONITOR=100 FNC TARGMAX=NAMES:1,LIST:1,KICK:1,WHOIS:1,PRIVMSG:4,NOTICE:4,ACCEPT:,MONITOR: :are supported by this server')
        self.swrite(irc.RPL_ISUPPORT, 'EXTBAN=$,ajrxz WHOX CLIENTVER=3.0 SAFELIST ELIST=CTU :are supported by this server')
        self.swrite(irc.RPL_LUSERCLIENT, ':There are 171 users and 98473 invisible on 27 servers')
        self.swrite(irc.RPL_LUSEROP, '24 :IRC Operators online')
        self.swrite(irc.RPL_LUSERUNKNOWN, '15 :unknown connection(s)')
        self.swrite(irc.RPL_LUSERCHANNELS, '51488 :channels formed')
        self.swrite(irc.RPL_LUSERME, ':I have 7817 selfs and 1 servers')

        # Sending the MOTD seems be required for Pidgin to connect.
        self.swrite(irc.RPL_MOTDSTART,
                      ':- pickups Message of the Day - ')
        self.swrite(irc.RPL_MOTD, ':- insert MOTD here')
        self.swrite(irc.RPL_MOTD, ':- insert MOTD here pt 2')
        self.swrite(irc.RPL_ENDOFMOTD, ':End of /MOTD command.')
        self.userMode(self.nickname, "+i")
        #self.uwrite('MODE', self.nickname, ':+i')


