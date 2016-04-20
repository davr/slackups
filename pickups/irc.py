# -*- test-case-name: twisted.words.test.test_irc -*-
# Copyright (c) Twisted Matrix Laboratories.
# See LICENSE for details.

"""
Internet Relay Chat protocol for client and server.

Future Plans
============

The way the IRCClient class works here encourages people to implement
IRC clients by subclassing the ephemeral protocol class, and it tends
to end up with way more state than it should for an object which will
be destroyed as soon as the TCP transport drops.  Someone oughta do
something about that, ya know?

The DCC support needs to have more hooks for the client for it to be
able to ask the user things like "Do you want to accept this session?"
and "Transfer #2 is 67% done." and otherwise manage the DCC sessions.

Test coverage needs to be better.

@var MAX_COMMAND_LENGTH: The maximum length of a command, as defined by RFC
    2812 section 2.3.

@var attributes: Singleton instance of L{_CharacterAttributes}, used for
    constructing formatted text information.

@author: Kevin Turner

@see: RFC 1459: Internet Relay Chat Protocol
@see: RFC 2812: Internet Relay Chat: Client Protocol
@see: U{The Client-To-Client-Protocol
<http://www.irchelp.org/irchelp/rfc/ctcpspec.html>}
"""

import errno, os, random, re, stat, struct, sys, time, types, traceback
import operator
import string, socket
import textwrap
import shlex
import logging
from os import path

#from twisted.internet import reactor, protocol, task
#from twisted.persisted import styles
#from twisted.protocols import basic
#from twisted.python import log, reflect, _textattributes

logger = logging.getLogger(__name__)
                
NUL = chr(0)
CR = chr(13)
NL = chr(10)
LF = NL
SPC = chr(32)

# This includes the CRLF terminator characters.
MAX_COMMAND_LENGTH = 512

CHANNEL_PREFIXES = '&#!+'

class IRCBadMessage(Exception):
    pass

class IRCPasswordMismatch(Exception):
    pass



class IRCBadModes(ValueError):
    """
    A malformed mode was encountered while attempting to parse a mode string.
    """



def parsemsg(s):
    """
    Breaks a message from an IRC server into its prefix, command, and
    arguments.

    @param s: The message to break.
    @type s: L{bytes}

    @return: A tuple of (prefix, command, args).
    @rtype: L{tuple}
    """
    prefix = ''
    trailing = []
    if not s:
        raise IRCBadMessage("Empty line.")
    if s[0] == ':':
        prefix, s = s[1:].split(' ', 1)
    if s.find(' :') != -1:
        s, trailing = s.split(' :', 1)
        args = s.split()
        args.append(trailing)
    else:
        args = s.split()
    command = args.pop(0)
    return prefix, command, args



def split(str, length=80):
    """
    Split a string into multiple lines.

    Whitespace near C{str[length]} will be preferred as a breaking point.
    C{"\\n"} will also be used as a breaking point.

    @param str: The string to split.
    @type str: C{str}

    @param length: The maximum length which will be allowed for any string in
        the result.
    @type length: C{int}

    @return: C{list} of C{str}
    """
    return [chunk
            for line in str.split('\n')
            for chunk in textwrap.wrap(line, length)]


def _intOrDefault(value, default=None):
    """
    Convert a value to an integer if possible.

    @rtype: C{int} or type of L{default}
    @return: An integer when C{value} can be converted to an integer,
        otherwise return C{default}
    """
    if value:
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    return default



class UnhandledCommand(RuntimeError):
    """
    A command dispatcher could not locate an appropriate command handler.
    """



class _CommandDispatcherMixin(object):
    """
    Dispatch commands to handlers based on their name.

    Command handler names should be of the form C{prefix_commandName},
    where C{prefix} is the value specified by L{prefix}, and must
    accept the parameters as given to L{dispatch}.

    Attempting to mix this in more than once for a single class will cause
    strange behaviour, due to L{prefix} being overwritten.

    @type prefix: C{str}
    @ivar prefix: Command handler prefix, used to locate handler attributes
    """
    prefix = None

    def dispatch(self, commandName, *args):
        """
        Perform actual command dispatch.
        """
        def _getMethodName(command):
            return '%s_%s' % (self.prefix, command)

        def _getMethod(name):
            return getattr(self, _getMethodName(name), None)

        method = _getMethod(commandName)
        if method is not None:
            return method(*args)

        method = _getMethod('unknown')
        if method is None:
            raise UnhandledCommand("No handler for %r could be found" % (_getMethodName(commandName),))
        return method(commandName, *args)





def parseModes(modes, params, paramModes=('', '')):
    """
    Parse an IRC mode string.

    The mode string is parsed into two lists of mode changes (added and
    removed), with each mode change represented as C{(mode, param)} where mode
    is the mode character, and param is the parameter passed for that mode, or
    C{None} if no parameter is required.

    @type modes: C{str}
    @param modes: Modes string to parse.

    @type params: C{list}
    @param params: Parameters specified along with L{modes}.

    @type paramModes: C{(str, str)}
    @param paramModes: A pair of strings (C{(add, remove)}) that indicate which modes take
        parameters when added or removed.

    @returns: Two lists of mode changes, one for modes added and the other for
        modes removed respectively, mode changes in each list are represented as
        C{(mode, param)}.
    """
    if len(modes) == 0:
        raise IRCBadModes('Empty mode string')

    if modes[0] not in '+-':
        raise IRCBadModes('Malformed modes string: %r' % (modes,))

    changes = ([], [])

    direction = None
    count = -1
    for ch in modes:
        if ch in '+-':
            if count == 0:
                raise IRCBadModes('Empty mode sequence: %r' % (modes,))
            direction = '+-'.index(ch)
            count = 0
        else:
            param = None
            if ch in paramModes[direction]:
                try:
                    param = params.pop(0)
                except IndexError:
                    raise IRCBadModes('Not enough parameters: %r' % (ch,))
            changes[direction].append((ch, param))
            count += 1

    if len(params) > 0:
        raise IRCBadModes('Too many parameters: %r %r' % (modes, params))

    if count == 0:
        raise IRCBadModes('Empty mode sequence: %r' % (modes,))

    return changes



class IRC:
    """
    Internet Relay Chat server protocol.
    """

    buffer = ""
    hostname = 'pickups.davr.org'

    encoding = 'utf-8'

    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.nickname = False
        self.username = False


    def connectionMade(self):
        if self.hostname is None:
            self.hostname = socket.getfqdn()

    def sendLine(self, line):
        print("Sending: '%s'"%line.encode('utf-8'))
        line = (line+CR+LF).encode(self.encoding)
        self.writer.write(line)


    def sendMessage(self, command, *parameter_list, **prefix):
        """
        Send a line formatted as an IRC message.

        First argument is the command, all subsequent arguments are parameters
        to that command.  If a prefix is desired, it may be specified with the
        keyword argument 'prefix'.
        """
        if not command:
            raise ValueError("IRC message requires a command.")

        if ' ' in command or command[0] == ':':
            # Not the ONLY way to screw up, but provides a little
            # sanity checking to catch likely dumb mistakes.
            raise ValueError("Somebody screwed up, 'cuz this doesn't" \
                  " look like a command to me: %s" % command)

        line = ' '.join([command] + list(parameter_list))
        if 'prefix' in prefix:
            line = ":%s %s" % (prefix['prefix'], line)
        self.sendLine(line)

        if len(parameter_list) > 15:
            logger.info("Message has %d parameters (RFC allows 15):\n%s" %
                    (len(parameter_list), line))

    def swrite(self, command, *parameter_list):
        self.sendMessage(command, self.nickname, *parameter_list, prefix=self.hostname)

    def dataReceived(self, data):
        """
        This hack is to support mIRC, which sends LF only, even though the RFC
        says CRLF.  (Also, the flexibility of LineReceiver to turn "line mode"
        on and off was not required.)
        """

        line = data

        if len(line) <= 2:
            # This is a blank line, at best.
            return
        if line[-1] == CR:
            line = line[:-1]
        prefix, command, params = parsemsg(line)
        # mIRC is a big pile of doo-doo
        command = command.upper()
        # DEBUG: logger.info( "%s %s %s" % (prefix, command, params))

        self.handleCommand(command, prefix, params)

    def readline(self):
        return self.reader.readline()

    def handleCommand(self, command, prefix, params):
        """
        Determine the function to call for the given command and call it with
        the given arguments.

        @param command: The IRC command to determine the function for.
        @type command: L{bytes}

        @param prefix: The prefix of the IRC message (as returned by
            L{parsemsg}).
        @type prefix: L{bytes}

        @param params: A list of parameters to call the function with.
        @type params: L{list}
        """
        method = getattr(self, "irc_%s" % command, None)
        try:
            if method is not None:
                method(prefix, params)
            else:
                self.irc_unknown(prefix, command, params)
        except:
            logger.error("Error raised handling IRC command %s",command)
            traceback.print_exc()


    def irc_unknown(self, prefix, command, params):
        """
        Called by L{handleCommand} on a command that doesn't have a defined
        handler. Subclasses should override this method.
        """
        logger.error("Unknown command: %s - %s - %s",prefix,command,params)
        #raise NotImplementedError(command, prefix, params)


    # Helper methods
    def privmsg(self, sender, recip, message):
        """
        Send a message to a channel or user

        @type sender: C{str} or C{unicode}
        @param sender: Who is sending this message.  Should be of the form
            username!ident@hostmask (unless you know better!).

        @type recip: C{str} or C{unicode}
        @param recip: The recipient of this message.  If a channel, it must
            start with a channel prefix.

        @type message: C{str} or C{unicode}
        @param message: The message being sent.
        """
        messages = message.replace("\r\n","\n").split("\n")
        for message in messages:
            self.sendLine(":%s PRIVMSG %s :%s" % (sender, recip, lowQuote(message)))


    def notice(self, sender, recip, message):
        """
        Send a "notice" to a channel or user.

        Notices differ from privmsgs in that the RFC claims they are different.
        Robots are supposed to send notices and not respond to them.  Clients
        typically display notices differently from privmsgs.

        @type sender: C{str} or C{unicode}
        @param sender: Who is sending this message.  Should be of the form
            username!ident@hostmask (unless you know better!).

        @type recip: C{str} or C{unicode}
        @param recip: The recipient of this message.  If a channel, it must
            start with a channel prefix.

        @type message: C{str} or C{unicode}
        @param message: The message being sent.
        """
        self.sendLine(":%s NOTICE %s :%s" % (sender, recip, message))


    def action(self, sender, recip, message):
        """
        Send an action to a channel or user.

        @type sender: C{str} or C{unicode}
        @param sender: Who is sending this message.  Should be of the form
            username!ident@hostmask (unless you know better!).

        @type recip: C{str} or C{unicode}
        @param recip: The recipient of this message.  If a channel, it must
            start with a channel prefix.

        @type message: C{str} or C{unicode}
        @param message: The action being sent.
        """
        self.sendLine(":%s ACTION %s :%s" % (sender, recip, message))


    def topic(self, user, channel, topic, author=None):
        """
        Send the topic to a user.

        @type user: C{str} or C{unicode}
        @param user: The user receiving the topic.  Only their nickname, not
            the full hostmask.

        @type channel: C{str} or C{unicode}
        @param channel: The channel for which this is the topic.

        @type topic: C{str} or C{unicode} or C{None}
        @param topic: The topic string, unquoted, or None if there is no topic.

        @type author: C{str} or C{unicode}
        @param author: If the topic is being changed, the full username and
            hostmask of the person changing it.
        """
        if author is None:
            if topic is None:
                self.sendLine(':%s %s %s %s :%s' % (
                    self.hostname, RPL_NOTOPIC, user, channel, 'No topic is set.'))
            else:
                self.sendLine(":%s %s %s %s :%s" % (
                    self.hostname, RPL_TOPIC, user, channel, lowQuote(topic)))
        else:
            self.sendLine(":%s TOPIC %s :%s" % (author, channel, lowQuote(topic)))


    def topicAuthor(self, user, channel, author, date):
        """
        Send the author of and time at which a topic was set for the given
        channel.

        This sends a 333 reply message, which is not part of the IRC RFC.

        @type user: C{str} or C{unicode}
        @param user: The user receiving the topic.  Only their nickname, not
            the full hostmask.

        @type channel: C{str} or C{unicode}
        @param channel: The channel for which this information is relevant.

        @type author: C{str} or C{unicode}
        @param author: The nickname (without hostmask) of the user who last set
            the topic.

        @type date: C{int}
        @param date: A POSIX timestamp (number of seconds since the epoch) at
            which the topic was last set.
        """
        self.sendLine(':%s %d %s %s %s %d' % (
            self.hostname, 333, user, channel, author, date))


    def names(self, user, channel, names):
        """
        Send the names of a channel's participants to a user.

        @type user: C{str} or C{unicode}
        @param user: The user receiving the name list.  Only their nickname,
            not the full hostmask.

        @type channel: C{str} or C{unicode}
        @param channel: The channel for which this is the namelist.

        @type names: C{list} of C{str} or C{unicode}
        @param names: The names to send.
        """
        # XXX If unicode is given, these limits are not quite correct
        prefixLength = len(channel) + len(user) + 10
        namesLength = 512 - prefixLength

        L = []
        count = 0
        for n in names:
            if count + len(n) + 1 > namesLength:
                self.sendLine(":%s %s %s = %s :%s" % (
                    self.hostname, RPL_NAMREPLY, user, channel, ' '.join(L)))
                L = [n]
                count = len(n)
            else:
                L.append(n)
                count += len(n) + 1
        if L:
            self.sendLine(":%s %s %s = %s :%s" % (
                self.hostname, RPL_NAMREPLY, user, channel, ' '.join(L)))
        self.sendLine(":%s %s %s %s :End of /NAMES list" % (
            self.hostname, RPL_ENDOFNAMES, user, channel))

    def list_channels(self, info):
        self.swrite(RPL_LISTSTART)
        for channel, num_users, topic in info:
            self.swrite(RPL_LIST, channel, str(num_users), ':{}'.format(topic))
        self.swrite(RPL_LISTEND, ':End of /LIST')


    def who(self, user, channel, memberInfo):
        """
        Send a list of users participating in a channel.

        @type user: C{str} or C{unicode}
        @param user: The user receiving this member information.  Only their
            nickname, not the full hostmask.

        @type channel: C{str} or C{unicode}
        @param channel: The channel for which this is the member information.

        @type memberInfo: C{list} of C{tuples}
        @param memberInfo: For each member of the given channel, a 7-tuple
            containing their username, their hostmask, the server to which they
            are connected, their nickname, the letter "H" or "G" (standing for
            "Here" or "Gone"), the hopcount from C{user} to this member, and
            this member's real name.
        """
        for info in memberInfo:
            (username, hostmask, server, nickname, flag, hops, realName) = info
            assert flag in ("H", "G")
            self.sendLine(":%s %s %s %s %s %s %s %s %s :%d %s" % (
                self.hostname, RPL_WHOREPLY, user, channel,
                username, hostmask, server, nickname, flag, hops, realName))

        self.sendLine(":%s %s %s %s :End of /WHO list." % (
            self.hostname, RPL_ENDOFWHO, user, channel))


    def whois(self, user, nick, username, hostname, realName, server, serverInfo, oper, idle, signOn, channels):
        """
        Send information about the state of a particular user.

        @type user: C{str} or C{unicode}
        @param user: The user receiving this information.  Only their nickname,
            not the full hostmask.

        @type nick: C{str} or C{unicode}
        @param nick: The nickname of the user this information describes.

        @type username: C{str} or C{unicode}
        @param username: The user's username (eg, ident response)

        @type hostname: C{str}
        @param hostname: The user's hostmask

        @type realName: C{str} or C{unicode}
        @param realName: The user's real name

        @type server: C{str} or C{unicode}
        @param server: The name of the server to which the user is connected

        @type serverInfo: C{str} or C{unicode}
        @param serverInfo: A descriptive string about that server

        @type oper: C{bool}
        @param oper: Indicates whether the user is an IRC operator

        @type idle: C{int}
        @param idle: The number of seconds since the user last sent a message

        @type signOn: C{int}
        @param signOn: A POSIX timestamp (number of seconds since the epoch)
            indicating the time the user signed on

        @type channels: C{list} of C{str} or C{unicode}
        @param channels: A list of the channels which the user is participating in
        """
        self.sendLine(":%s %s %s %s %s %s * :%s" % (
            self.hostname, RPL_WHOISUSER, user, nick, username, hostname, realName))
        self.sendLine(":%s %s %s %s %s :%s" % (
            self.hostname, RPL_WHOISSERVER, user, nick, server, serverInfo))
        if oper:
            self.sendLine(":%s %s %s %s :is an IRC operator" % (
                self.hostname, RPL_WHOISOPERATOR, user, nick))
        self.sendLine(":%s %s %s %s %d %d :seconds idle, signon time" % (
            self.hostname, RPL_WHOISIDLE, user, nick, idle, signOn))
        self.sendLine(":%s %s %s %s :%s" % (
            self.hostname, RPL_WHOISCHANNELS, user, nick, ' '.join(channels)))
        self.sendLine(":%s %s %s %s :End of WHOIS list." % (
            self.hostname, RPL_ENDOFWHOIS, user, nick))


    def pong(self, params):
        self.swrite('PONG', params[-1])

    def join(self, who, where):
        """
        Send a join message.

        @type who: C{str} or C{unicode}
        @param who: The name of the user joining.  Should be of the form
            username!ident@hostmask (unless you know better!).

        @type where: C{str} or C{unicode}
        @param where: The channel the user is joining.
        """
        self.sendLine(":%s JOIN %s" % (who, where))

    def nick(self, oldnick, newnick):
        self.sendLine(":%s NICK %s" % (oldnick, newnick))

    def part(self, who, where, reason=None):
        """
        Send a part message.

        @type who: C{str} or C{unicode}
        @param who: The name of the user joining.  Should be of the form
            username!ident@hostmask (unless you know better!).

        @type where: C{str} or C{unicode}
        @param where: The channel the user is joining.

        @type reason: C{str} or C{unicode}
        @param reason: A string describing the misery which caused this poor
            soul to depart.
        """
        if reason:
            self.sendLine(":%s PART %s :%s" % (who, where, reason))
        else:
            self.sendLine(":%s PART %s" % (who, where))

    def userMode(self, user, modestr):
        self.sendLine(":%s MODE %s %s" % (self.hostname, user, modestr))

    def channelMode(self, user, channel, mode, *args):
        """
        Send information about the mode of a channel.

        @type user: C{str} or C{unicode}
        @param user: The user receiving the name list.  Only their nickname,
            not the full hostmask.

        @type channel: C{str} or C{unicode}
        @param channel: The channel for which this is the namelist.

        @type mode: C{str}
        @param mode: A string describing this channel's modes.

        @param args: Any additional arguments required by the modes.
        """
        self.sendLine(":%s %s %s %s %s %s" % (
            self.hostname, RPL_CHANNELMODEIS, user, channel, mode, ' '.join(args)))



class ServerSupportedFeatures(_CommandDispatcherMixin):
    """
    Handle ISUPPORT messages.

    Feature names match those in the ISUPPORT RFC draft identically.

    Information regarding the specifics of ISUPPORT was gleaned from
    <http://www.irc.org/tech_docs/draft-brocklesby-irc-isupport-03.txt>.
    """
    prefix = 'isupport'

    def __init__(self):
        self._features = {
            'CHANNELLEN': 200,
            'CHANTYPES': tuple('#&'),
            'MODES': 3,
            'NICKLEN': 9,
            'PREFIX': self._parsePrefixParam('(ovh)@+%'),
            # The ISUPPORT draft explicitly says that there is no default for
            # CHANMODES, but we're defaulting it here to handle the case where
            # the IRC server doesn't send us any ISUPPORT information, since
            # IRCClient.getChannelModeParams relies on this value.
            'CHANMODES': self._parseChanModesParam(['b', '', 'lk'])}


    def _splitParamArgs(cls, params, valueProcessor=None):
        """
        Split ISUPPORT parameter arguments.

        Values can optionally be processed by C{valueProcessor}.

        For example::

            >>> ServerSupportedFeatures._splitParamArgs(['A:1', 'B:2'])
            (('A', '1'), ('B', '2'))

        @type params: C{iterable} of C{str}

        @type valueProcessor: C{callable} taking {str}
        @param valueProcessor: Callable to process argument values, or C{None}
            to perform no processing

        @rtype: C{list} of C{(str, object)}
        @return: Sequence of C{(name, processedValue)}
        """
        if valueProcessor is None:
            valueProcessor = lambda x: x

        def _parse():
            for param in params:
                if ':' not in param:
                    param += ':'
                a, b = param.split(':', 1)
                yield a, valueProcessor(b)
        return list(_parse())
    _splitParamArgs = classmethod(_splitParamArgs)


    def _unescapeParamValue(cls, value):
        """
        Unescape an ISUPPORT parameter.

        The only form of supported escape is C{\\xHH}, where HH must be a valid
        2-digit hexadecimal number.

        @rtype: C{str}
        """
        def _unescape():
            parts = value.split('\\x')
            # The first part can never be preceded by the escape.
            yield parts.pop(0)
            for s in parts:
                octet, rest = s[:2], s[2:]
                try:
                    octet = int(octet, 16)
                except ValueError:
                    raise ValueError('Invalid hex octet: %r' % (octet,))
                yield chr(octet) + rest

        if '\\x' not in value:
            return value
        return ''.join(_unescape())
    _unescapeParamValue = classmethod(_unescapeParamValue)


    def _splitParam(cls, param):
        """
        Split an ISUPPORT parameter.

        @type param: C{str}

        @rtype: C{(str, list)}
        @return C{(key, arguments)}
        """
        if '=' not in param:
            param += '='
        key, value = param.split('=', 1)
        return key, map(cls._unescapeParamValue, value.split(','))
    _splitParam = classmethod(_splitParam)


    def _parsePrefixParam(cls, prefix):
        """
        Parse the ISUPPORT "PREFIX" parameter.

        The order in which the parameter arguments appear is significant, the
        earlier a mode appears the more privileges it gives.

        @rtype: C{dict} mapping C{str} to C{(str, int)}
        @return: A dictionary mapping a mode character to a two-tuple of
            C({symbol, priority)}, the lower a priority (the lowest being
            C{0}) the more privileges it gives
        """
        if not prefix:
            return None
        if prefix[0] != '(' and ')' not in prefix:
            raise ValueError('Malformed PREFIX parameter')
        modes, symbols = prefix.split(')', 1)
        symbols = zip(symbols, xrange(len(symbols)))
        modes = modes[1:]
        return dict(zip(modes, symbols))
    _parsePrefixParam = classmethod(_parsePrefixParam)


    def _parseChanModesParam(self, params):
        """
        Parse the ISUPPORT "CHANMODES" parameter.

        See L{isupport_CHANMODES} for a detailed explanation of this parameter.
        """
        names = ('addressModes', 'param', 'setParam', 'noParam')
        if len(params) > len(names):
            raise ValueError(
                'Expecting a maximum of %d channel mode parameters, got %d' % (
                    len(names), len(params)))
        items = map(lambda key, value: (key, value or ''), names, params)
        return dict(items)
    _parseChanModesParam = classmethod(_parseChanModesParam)


    def getFeature(self, feature, default=None):
        """
        Get a server supported feature's value.

        A feature with the value C{None} is equivalent to the feature being
        unsupported.

        @type feature: C{str}
        @param feature: Feature name

        @type default: C{object}
        @param default: The value to default to, assuming that C{feature}
            is not supported

        @return: Feature value
        """
        return self._features.get(feature, default)


    def hasFeature(self, feature):
        """
        Determine whether a feature is supported or not.

        @rtype: C{bool}
        """
        return self.getFeature(feature) is not None


    def parse(self, params):
        """
        Parse ISUPPORT parameters.

        If an unknown parameter is encountered, it is simply added to the
        dictionary, keyed by its name, as a tuple of the parameters provided.

        @type params: C{iterable} of C{str}
        @param params: Iterable of ISUPPORT parameters to parse
        """
        for param in params:
            key, value = self._splitParam(param)
            if key.startswith('-'):
                self._features.pop(key[1:], None)
            else:
                self._features[key] = self.dispatch(key, value)


    def isupport_unknown(self, command, params):
        """
        Unknown ISUPPORT parameter.
        """
        return tuple(params)


    def isupport_CHANLIMIT(self, params):
        """
        The maximum number of each channel type a user may join.
        """
        return self._splitParamArgs(params, _intOrDefault)


    def isupport_CHANMODES(self, params):
        """
        Available channel modes.

        There are 4 categories of channel mode::

            addressModes - Modes that add or remove an address to or from a
            list, these modes always take a parameter.

            param - Modes that change a setting on a channel, these modes
            always take a parameter.

            setParam - Modes that change a setting on a channel, these modes
            only take a parameter when being set.

            noParam - Modes that change a setting on a channel, these modes
            never take a parameter.
        """
        try:
            return self._parseChanModesParam(params)
        except ValueError:
            return self.getFeature('CHANMODES')


    def isupport_CHANNELLEN(self, params):
        """
        Maximum length of a channel name a client may create.
        """
        return _intOrDefault(params[0], self.getFeature('CHANNELLEN'))


    def isupport_CHANTYPES(self, params):
        """
        Valid channel prefixes.
        """
        return tuple(params[0])


    def isupport_EXCEPTS(self, params):
        """
        Mode character for "ban exceptions".

        The presence of this parameter indicates that the server supports
        this functionality.
        """
        return params[0] or 'e'


    def isupport_IDCHAN(self, params):
        """
        Safe channel identifiers.

        The presence of this parameter indicates that the server supports
        this functionality.
        """
        return self._splitParamArgs(params)


    def isupport_INVEX(self, params):
        """
        Mode character for "invite exceptions".

        The presence of this parameter indicates that the server supports
        this functionality.
        """
        return params[0] or 'I'


    def isupport_KICKLEN(self, params):
        """
        Maximum length of a kick message a client may provide.
        """
        return _intOrDefault(params[0])


    def isupport_MAXLIST(self, params):
        """
        Maximum number of "list modes" a client may set on a channel at once.

        List modes are identified by the "addressModes" key in CHANMODES.
        """
        return self._splitParamArgs(params, _intOrDefault)


    def isupport_MODES(self, params):
        """
        Maximum number of modes accepting parameters that may be sent, by a
        client, in a single MODE command.
        """
        return _intOrDefault(params[0])


    def isupport_NETWORK(self, params):
        """
        IRC network name.
        """
        return params[0]


    def isupport_NICKLEN(self, params):
        """
        Maximum length of a nickname the client may use.
        """
        return _intOrDefault(params[0], self.getFeature('NICKLEN'))


    def isupport_PREFIX(self, params):
        """
        Mapping of channel modes that clients may have to status flags.
        """
        try:
            return self._parsePrefixParam(params[0])
        except ValueError:
            return self.getFeature('PREFIX')


    def isupport_SAFELIST(self, params):
        """
        Flag indicating that a client may request a LIST without being
        disconnected due to the large amount of data generated.
        """
        return True


    def isupport_STATUSMSG(self, params):
        """
        The server supports sending messages to only to clients on a channel
        with a specific status.
        """
        return params[0]


    def isupport_TARGMAX(self, params):
        """
        Maximum number of targets allowable for commands that accept multiple
        targets.
        """
        return dict(self._splitParamArgs(params, _intOrDefault))


    def isupport_TOPICLEN(self, params):
        """
        Maximum length of a topic that may be set.
        """
        return _intOrDefault(params[0])



def dccParseAddress(address):
    if '.' in address:
        pass
    else:
        try:
            address = long(address)
        except ValueError:
            raise IRCBadMessage("Indecipherable address %r" % (address,))
        else:
            address = (
                (address >> 24) & 0xFF,
                (address >> 16) & 0xFF,
                (address >> 8) & 0xFF,
                address & 0xFF,
                )
            address = '.'.join(map(str,address))
    return address


class DccFileReceiveBasic:
    """
    Bare protocol to receive a Direct Client Connection SEND stream.

    This does enough to keep the other guy talking, but you'll want to extend
    my dataReceived method to *do* something with the data I get.

    @ivar bytesReceived: An integer representing the number of bytes of data
        received.
    @type bytesReceived: L{int}
    """

    bytesReceived = 0

    def __init__(self, resumeOffset=0):
        """
        @param resumeOffset: An integer representing the amount of bytes from
            where the transfer of data should be resumed.
        @type resumeOffset: L{int}
        """
        self.bytesReceived = resumeOffset
        self.resume = (resumeOffset != 0)

    def dataReceived(self, data):
        """
        See: L{protocol.Protocol.dataReceived}

        Warning: This just acknowledges to the remote host that the data has
        been received; it doesn't I{do} anything with the data, so you'll want
        to override this.
        """
        self.bytesReceived = self.bytesReceived + len(data)
        self.transport.write(struct.pack('!i', self.bytesReceived))


class DccSendProtocol:
    """
    Protocol for an outgoing Direct Client Connection SEND.

    @ivar blocksize: An integer representing the size of an individual block of
        data.
    @type blocksize: L{int}

    @ivar file: The file to be sent.  This can be either a file object or
        simply the name of the file.
    @type file: L{file} or L{bytes}

    @ivar bytesSent: An integer representing the number of bytes sent.
    @type bytesSent: L{int}

    @ivar completed: An integer representing whether the transfer has been
        completed or not.
    @type completed: L{int}

    @ivar connected: An integer representing whether the connection has been
        established or not.
    @type connected: L{int}
    """

    blocksize = 1024
    file = None
    bytesSent = 0
    completed = 0
    connected = 0

    def __init__(self, file):
        if type(file) is types.StringType:
            self.file = open(file, 'r')

    def connectionMade(self):
        self.connected = 1
        self.sendBlock()

    def dataReceived(self, data):
        # XXX: Do we need to check to see if len(data) != fmtsize?

        bytesShesGot = struct.unpack("!I", data)
        if bytesShesGot < self.bytesSent:
            # Wait for her.
            # XXX? Add some checks to see if we've stalled out?
            return
        elif bytesShesGot > self.bytesSent:
            # self.transport.log("DCC SEND %s: She says she has %d bytes "
            #                    "but I've only sent %d.  I'm stopping "
            #                    "this screwy transfer."
            #                    % (self.file,
            #                       bytesShesGot, self.bytesSent))
            self.transport.loseConnection()
            return

        self.sendBlock()

    def sendBlock(self):
        block = self.file.read(self.blocksize)
        if block:
            self.transport.write(block)
            self.bytesSent = self.bytesSent + len(block)
        else:
            # Nothing more to send, transfer complete.
            self.transport.loseConnection()
            self.completed = 1

    def connectionLost(self, reason):
        self.connected = 0
        if hasattr(self.file, "close"):
            self.file.close()


class DccSendFactory:
    protocol = DccSendProtocol
    def __init__(self, file):
        self.file = file

    def buildProtocol(self, connection):
        p = self.protocol(self.file)
        p.factory = self
        return p


def fileSize(file):
    """
    I'll try my damndest to determine the size of this file object.

    @param file: The file object to determine the size of.
    @type file: L{file}

    @rtype: L{int} or L{None}
    @return: The size of the file object as an integer if it can be determined,
        otherwise return L{None}.
    """
    size = None
    if hasattr(file, "fileno"):
        fileno = file.fileno()
        try:
            stat_ = os.fstat(fileno)
            size = stat_[stat.ST_SIZE]
        except:
            pass
        else:
            return size

    if hasattr(file, "name") and path.exists(file.name):
        try:
            size = path.getsize(file.name)
        except:
            pass
        else:
            return size

    if hasattr(file, "seek") and hasattr(file, "tell"):
        try:
            try:
                file.seek(0, 2)
                size = file.tell()
            finally:
                file.seek(0, 0)
        except:
            pass
        else:
            return size

    return size

class DccChat:
    """
    Direct Client Connection protocol type CHAT.

    DCC CHAT is really just your run o' the mill basic.LineReceiver
    protocol.  This class only varies from that slightly, accepting
    either LF or CR LF for a line delimeter for incoming messages
    while always using CR LF for outgoing.

    The lineReceived method implemented here uses the DCC connection's
    'client' attribute (provided upon construction) to deliver incoming
    lines from the DCC chat via IRCClient's normal privmsg interface.
    That's something of a spoof, which you may well want to override.
    """

    queryData = None
    delimiter = CR + NL
    client = None
    remoteParty = None
    buffer = ""

    def __init__(self, client, queryData=None):
        """
        Initialize a new DCC CHAT session.

        queryData is a 3-tuple of
        (fromUser, targetUserOrChannel, data)
        as received by the CTCP query.

        (To be honest, fromUser is the only thing that's currently
        used here. targetUserOrChannel is potentially useful, while
        the 'data' argument is soley for informational purposes.)
        """
        self.client = client
        if queryData:
            self.queryData = queryData
            self.remoteParty = self.queryData[0]

    def dataReceived(self, data):
        self.buffer = self.buffer + data
        lines = self.buffer.split(LF)
        # Put the (possibly empty) element after the last LF back in the
        # buffer
        self.buffer = lines.pop()

        for line in lines:
            if line[-1] == CR:
                line = line[:-1]
            self.lineReceived(line)

    def lineReceived(self, line):
        logger.info("DCC CHAT<%s> %s" % (self.remoteParty, line))
        self.client.privmsg(self.remoteParty,
                            self.client.nickname, line)


class DccChatFactory:
    protocol = DccChat
    noisy = 0
    def __init__(self, client, queryData):
        self.client = client
        self.queryData = queryData


    def buildProtocol(self, addr):
        p = self.protocol(client=self.client, queryData=self.queryData)
        p.factory = self
        return p


    def clientConnectionFailed(self, unused_connector, unused_reason):
        self.client.dcc_sessions.remove(self)

    def clientConnectionLost(self, unused_connector, unused_reason):
        self.client.dcc_sessions.remove(self)


def dccDescribe(data):
    """
    Given the data chunk from a DCC query, return a descriptive string.

    @param data: The data from a DCC query.
    @type data: L{bytes}

    @rtype: L{bytes}
    @return: A descriptive string.
    """

    orig_data = data
    data = data.split()
    if len(data) < 4:
        return orig_data

    (dcctype, arg, address, port) = data[:4]

    if '.' in address:
        pass
    else:
        try:
            address = long(address)
        except ValueError:
            pass
        else:
            address = (
                (address >> 24) & 0xFF,
                (address >> 16) & 0xFF,
                (address >> 8) & 0xFF,
                address & 0xFF,
                )
            address = '.'.join(map(str, address))

    if dcctype == 'SEND':
        filename = arg

        size_txt = ''
        if len(data) >= 5:
            try:
                size = int(data[4])
                size_txt = ' of size %d bytes' % (size,)
            except ValueError:
                pass

        dcc_text = ("SEND for file '%s'%s at host %s, port %s"
                    % (filename, size_txt, address, port))
    elif dcctype == 'CHAT':
        dcc_text = ("CHAT for host %s, port %s"
                    % (address, port))
    else:
        dcc_text = orig_data

    return dcc_text


class DccFileReceive:
    """
    Higher-level coverage for getting a file from DCC SEND.

    I allow you to change the file's name and destination directory.  I won't
    overwrite an existing file unless I've been told it's okay to do so.  If
    passed the resumeOffset keyword argument I will attempt to resume the file
    from that amount of bytes.

    XXX: I need to let the client know when I am finished.
    XXX: I need to decide how to keep a progress indicator updated.
    XXX: Client needs a way to tell me "Do not finish until I say so."
    XXX: I need to make sure the client understands if the file cannot be written.

    @ivar filename: The name of the file to get.
    @type filename: L{bytes}

    @ivar fileSize: The size of the file to get, which has a default value of
        C{-1} if the size of the file was not specified in the DCC SEND
        request.
    @type fileSize: L{int}

    @ivar destDir: The destination directory for the file to be received.
    @type destDir: L{bytes}

    @ivar overwrite: An integer representing whether an existing file should be
        overwritten or not.  This initially is an L{int} but can be modified to
        be a L{bool} using the L{set_overwrite} method.
    @type overwrite: L{int} or L{bool}

    @ivar queryData: queryData is a 3-tuple of (user, channel, data).
    @type queryData: L{tuple}

    @ivar fromUser: This is the hostmask of the requesting user and is found at
        index 0 of L{queryData}.
    @type fromUser: L{bytes}
    """

    filename = 'dcc'
    fileSize = -1
    destDir = '.'
    overwrite = 0
    fromUser = None
    queryData = None

    def __init__(self, filename, fileSize=-1, queryData=None,
                 destDir='.', resumeOffset=0):
        DccFileReceiveBasic.__init__(self, resumeOffset=resumeOffset)
        self.filename = filename
        self.destDir = destDir
        self.fileSize = fileSize

        if queryData:
            self.queryData = queryData
            self.fromUser = self.queryData[0]

    def set_directory(self, directory):
        """
        Set the directory where the downloaded file will be placed.

        May raise OSError if the supplied directory path is not suitable.

        @param directory: The directory where the file to be received will be
            placed.
        @type directory: L{bytes}
        """
        if not path.exists(directory):
            raise OSError(errno.ENOENT, "You see no directory there.",
                          directory)
        if not path.isdir(directory):
            raise OSError(errno.ENOTDIR, "You cannot put a file into "
                          "something which is not a directory.",
                          directory)
        if not os.access(directory, os.X_OK | os.W_OK):
            raise OSError(errno.EACCES,
                          "This directory is too hard to write in to.",
                          directory)
        self.destDir = directory

    def set_filename(self, filename):
        """
        Change the name of the file being transferred.

        This replaces the file name provided by the sender.

        @param filename: The new name for the file.
        @type filename: L{bytes}
        """
        self.filename = filename

    def set_overwrite(self, boolean):
        """
        May I overwrite existing files?

        @param boolean: A boolean value representing whether existing files
            should be overwritten or not.
        @type boolean: L{bool}
        """
        self.overwrite = boolean


    # Protocol-level methods.

    def connectionMade(self):
        dst = path.abspath(path.join(self.destDir,self.filename))
        exists = path.exists(dst)
        if self.resume and exists:
            # I have been told I want to resume, and a file already
            # exists - Here we go
            self.file = open(dst, 'ab')
            logger.info("Attempting to resume %s - starting from %d bytes" %
                    (self.file, self.file.tell()))
        elif self.overwrite or not exists:
            self.file = open(dst, 'wb')
        else:
            raise OSError(errno.EEXIST,
                          "There's a file in the way.  "
                          "Perhaps that's why you cannot open it.",
                          dst)

    def dataReceived(self, data):
        self.file.write(data)
        DccFileReceiveBasic.dataReceived(self, data)

        # XXX: update a progress indicator here?

    def connectionLost(self, reason):
        """
        When the connection is lost, I close the file.

        @param reason: The reason why the connection was lost.
        @type reason: L{Failure}
        """
        self.connected = 0
        logmsg = ("%s closed." % (self,))
        if self.fileSize > 0:
            logmsg = ("%s  %d/%d bytes received"
                      % (logmsg, self.bytesReceived, self.fileSize))
            if self.bytesReceived == self.fileSize:
                pass # Hooray!
            elif self.bytesReceived < self.fileSize:
                logmsg = ("%s (Warning: %d bytes short)"
                          % (logmsg, self.fileSize - self.bytesReceived))
            else:
                logmsg = ("%s (file larger than expected)"
                          % (logmsg,))
        else:
            logmsg = ("%s  %d bytes received"
                      % (logmsg, self.bytesReceived))

        if hasattr(self, 'file'):
            logmsg = "%s and written to %s.\n" % (logmsg, self.file.name)
            if hasattr(self.file, 'close'): self.file.close()

        # self.transport.log(logmsg)

    def __str__(self):
        if not self.connected:
            return "<Unconnected DccFileReceive object at %x>" % (id(self),)
        from_ = self.transport.getPeer()
        if self.fromUser:
            from_ = "%s (%s)" % (self.fromUser, from_)

        s = ("DCC transfer of '%s' from %s" % (self.filename, from_))
        return s

    def __repr__(self):
        s = ("<%s at %x: GET %s>"
             % (self.__class__, id(self), self.filename))
        return s


# CTCP constants and helper functions

X_DELIM = chr(1)

def ctcpExtract(message):
    """
    Extract CTCP data from a string.

    @return: A C{dict} containing two keys:
       - C{'extended'}: A list of CTCP (tag, data) tuples.
       - C{'normal'}: A list of strings which were not inside a CTCP delimiter.
    """
    extended_messages = []
    normal_messages = []
    retval = {'extended': extended_messages,
              'normal': normal_messages }

    messages = message.split(X_DELIM)
    odd = 0

    # X1 extended data X2 nomal data X3 extended data X4 normal...
    while messages:
        if odd:
            extended_messages.append(messages.pop(0))
        else:
            normal_messages.append(messages.pop(0))
        odd = not odd

    extended_messages[:] = filter(None, extended_messages)
    normal_messages[:] = filter(None, normal_messages)

    extended_messages[:] = map(ctcpDequote, extended_messages)
    for i in xrange(len(extended_messages)):
        m = extended_messages[i].split(SPC, 1)
        tag = m[0]
        if len(m) > 1:
            data = m[1]
        else:
            data = None

        extended_messages[i] = (tag, data)

    return retval

# CTCP escaping

M_QUOTE= chr(16)

mQuoteTable = {
    NUL: M_QUOTE + '0',
    NL: M_QUOTE + 'n',
    CR: M_QUOTE + 'r',
    M_QUOTE: M_QUOTE + M_QUOTE
    }

mDequoteTable = {}
for k, v in mQuoteTable.items():
    mDequoteTable[v[-1]] = k
del k, v

mEscape_re = re.compile('%s.' % (re.escape(M_QUOTE),), re.DOTALL)

def lowQuote(s):
    for c in (M_QUOTE, NUL, NL, CR):
        s = s.replace(c, mQuoteTable[c])
    return s

def lowDequote(s):
    def sub(matchobj, mDequoteTable=mDequoteTable):
        s = matchobj.group()[1]
        try:
            s = mDequoteTable[s]
        except KeyError:
            s = s
        return s

    return mEscape_re.sub(sub, s)

X_QUOTE = '\\'

xQuoteTable = {
    X_DELIM: X_QUOTE + 'a',
    X_QUOTE: X_QUOTE + X_QUOTE
    }

xDequoteTable = {}

for k, v in xQuoteTable.items():
    xDequoteTable[v[-1]] = k

xEscape_re = re.compile('%s.' % (re.escape(X_QUOTE),), re.DOTALL)

def ctcpQuote(s):
    for c in (X_QUOTE, X_DELIM):
        s = s.replace(c, xQuoteTable[c])
    return s

def ctcpDequote(s):
    def sub(matchobj, xDequoteTable=xDequoteTable):
        s = matchobj.group()[1]
        try:
            s = xDequoteTable[s]
        except KeyError:
            s = s
        return s

    return xEscape_re.sub(sub, s)

def ctcpStringify(messages):
    """
    @type messages: a list of extended messages.  An extended
    message is a (tag, data) tuple, where 'data' may be C{None}, a
    string, or a list of strings to be joined with whitespace.

    @returns: String
    """
    coded_messages = []
    for (tag, data) in messages:
        if data:
            if not isinstance(data, types.StringType):
                try:
                    # data as list-of-strings
                    data = " ".join(map(str, data))
                except TypeError:
                    # No?  Then use it's %s representation.
                    pass
            m = "%s %s" % (tag, data)
        else:
            m = str(tag)
        m = ctcpQuote(m)
        m = "%s%s%s" % (X_DELIM, m, X_DELIM)
        coded_messages.append(m)

    line = ''.join(coded_messages)
    return line


# Constants (from RFC 2812)
RPL_WELCOME = '001'
RPL_YOURHOST = '002'
RPL_CREATED = '003'
RPL_MYINFO = '004'
RPL_ISUPPORT = '005'
RPL_BOUNCE = '010'
RPL_USERHOST = '302'
RPL_ISON = '303'
RPL_AWAY = '301'
RPL_UNAWAY = '305'
RPL_NOWAWAY = '306'
RPL_WHOISUSER = '311'
RPL_WHOISSERVER = '312'
RPL_WHOISOPERATOR = '313'
RPL_WHOISIDLE = '317'
RPL_ENDOFWHOIS = '318'
RPL_WHOISCHANNELS = '319'
RPL_WHOWASUSER = '314'
RPL_ENDOFWHOWAS = '369'
RPL_LISTSTART = '321'
RPL_LIST = '322'
RPL_LISTEND = '323'
RPL_UNIQOPIS = '325'
RPL_CHANNELMODEIS = '324'
RPL_NOTOPIC = '331'
RPL_TOPIC = '332'
RPL_INVITING = '341'
RPL_SUMMONING = '342'
RPL_INVITELIST = '346'
RPL_ENDOFINVITELIST = '347'
RPL_EXCEPTLIST = '348'
RPL_ENDOFEXCEPTLIST = '349'
RPL_VERSION = '351'
RPL_WHOREPLY = '352'
RPL_ENDOFWHO = '315'
RPL_NAMREPLY = '353'
RPL_ENDOFNAMES = '366'
RPL_LINKS = '364'
RPL_ENDOFLINKS = '365'
RPL_BANLIST = '367'
RPL_ENDOFBANLIST = '368'
RPL_INFO = '371'
RPL_ENDOFINFO = '374'
RPL_MOTDSTART = '375'
RPL_MOTD = '372'
RPL_ENDOFMOTD = '376'
RPL_YOUREOPER = '381'
RPL_REHASHING = '382'
RPL_YOURESERVICE = '383'
RPL_TIME = '391'
RPL_USERSSTART = '392'
RPL_USERS = '393'
RPL_ENDOFUSERS = '394'
RPL_NOUSERS = '395'
RPL_TRACELINK = '200'
RPL_TRACECONNECTING = '201'
RPL_TRACEHANDSHAKE = '202'
RPL_TRACEUNKNOWN = '203'
RPL_TRACEOPERATOR = '204'
RPL_TRACEUSER = '205'
RPL_TRACESERVER = '206'
RPL_TRACESERVICE = '207'
RPL_TRACENEWTYPE = '208'
RPL_TRACECLASS = '209'
RPL_TRACERECONNECT = '210'
RPL_TRACELOG = '261'
RPL_TRACEEND = '262'
RPL_STATSLINKINFO = '211'
RPL_STATSCOMMANDS = '212'
RPL_ENDOFSTATS = '219'
RPL_STATSUPTIME = '242'
RPL_STATSOLINE = '243'
RPL_UMODEIS = '221'
RPL_SERVLIST = '234'
RPL_SERVLISTEND = '235'
RPL_LUSERCLIENT = '251'
RPL_LUSEROP = '252'
RPL_LUSERUNKNOWN = '253'
RPL_LUSERCHANNELS = '254'
RPL_LUSERME = '255'
RPL_ADMINME = '256'
RPL_ADMINLOC = '257'
RPL_ADMINLOC = '258'
RPL_ADMINEMAIL = '259'
RPL_TRYAGAIN = '263'
ERR_NOSUCHNICK = '401'
ERR_NOSUCHSERVER = '402'
ERR_NOSUCHCHANNEL = '403'
ERR_CANNOTSENDTOCHAN = '404'
ERR_TOOMANYCHANNELS = '405'
ERR_WASNOSUCHNICK = '406'
ERR_TOOMANYTARGETS = '407'
ERR_NOSUCHSERVICE = '408'
ERR_NOORIGIN = '409'
ERR_NORECIPIENT = '411'
ERR_NOTEXTTOSEND = '412'
ERR_NOTOPLEVEL = '413'
ERR_WILDTOPLEVEL = '414'
ERR_BADMASK = '415'
ERR_UNKNOWNCOMMAND = '421'
ERR_NOMOTD = '422'
ERR_NOADMININFO = '423'
ERR_FILEERROR = '424'
ERR_NONICKNAMEGIVEN = '431'
ERR_ERRONEUSNICKNAME = '432'
ERR_NICKNAMEINUSE = '433'
ERR_NICKCOLLISION = '436'
ERR_UNAVAILRESOURCE = '437'
ERR_USERNOTINCHANNEL = '441'
ERR_NOTONCHANNEL = '442'
ERR_USERONCHANNEL = '443'
ERR_NOLOGIN = '444'
ERR_SUMMONDISABLED = '445'
ERR_USERSDISABLED = '446'
ERR_NOTREGISTERED = '451'
ERR_NEEDMOREPARAMS = '461'
ERR_ALREADYREGISTRED = '462'
ERR_NOPERMFORHOST = '463'
ERR_PASSWDMISMATCH = '464'
ERR_YOUREBANNEDCREEP = '465'
ERR_YOUWILLBEBANNED = '466'
ERR_KEYSET = '467'
ERR_CHANNELISFULL = '471'
ERR_UNKNOWNMODE = '472'
ERR_INVITEONLYCHAN = '473'
ERR_BANNEDFROMCHAN = '474'
ERR_BADCHANNELKEY = '475'
ERR_BADCHANMASK = '476'
ERR_NOCHANMODES = '477'
ERR_BANLISTFULL = '478'
ERR_NOPRIVILEGES = '481'
ERR_CHANOPRIVSNEEDED = '482'
ERR_CANTKILLSERVER = '483'
ERR_RESTRICTED = '484'
ERR_UNIQOPPRIVSNEEDED = '485'
ERR_NOOPERHOST = '491'
ERR_NOSERVICEHOST = '492'
ERR_UMODEUNKNOWNFLAG = '501'
ERR_USERSDONTMATCH = '502'

# And hey, as long as the strings are already intern'd...
symbolic_to_numeric = {
    "RPL_WELCOME": '001',
    "RPL_YOURHOST": '002',
    "RPL_CREATED": '003',
    "RPL_MYINFO": '004',
    "RPL_ISUPPORT": '005',
    "RPL_BOUNCE": '010',
    "RPL_USERHOST": '302',
    "RPL_ISON": '303',
    "RPL_AWAY": '301',
    "RPL_UNAWAY": '305',
    "RPL_NOWAWAY": '306',
    "RPL_WHOISUSER": '311',
    "RPL_WHOISSERVER": '312',
    "RPL_WHOISOPERATOR": '313',
    "RPL_WHOISIDLE": '317',
    "RPL_ENDOFWHOIS": '318',
    "RPL_WHOISCHANNELS": '319',
    "RPL_WHOWASUSER": '314',
    "RPL_ENDOFWHOWAS": '369',
    "RPL_LISTSTART": '321',
    "RPL_LIST": '322',
    "RPL_LISTEND": '323',
    "RPL_UNIQOPIS": '325',
    "RPL_CHANNELMODEIS": '324',
    "RPL_NOTOPIC": '331',
    "RPL_TOPIC": '332',
    "RPL_INVITING": '341',
    "RPL_SUMMONING": '342',
    "RPL_INVITELIST": '346',
    "RPL_ENDOFINVITELIST": '347',
    "RPL_EXCEPTLIST": '348',
    "RPL_ENDOFEXCEPTLIST": '349',
    "RPL_VERSION": '351',
    "RPL_WHOREPLY": '352',
    "RPL_ENDOFWHO": '315',
    "RPL_NAMREPLY": '353',
    "RPL_ENDOFNAMES": '366',
    "RPL_LINKS": '364',
    "RPL_ENDOFLINKS": '365',
    "RPL_BANLIST": '367',
    "RPL_ENDOFBANLIST": '368',
    "RPL_INFO": '371',
    "RPL_ENDOFINFO": '374',
    "RPL_MOTDSTART": '375',
    "RPL_MOTD": '372',
    "RPL_ENDOFMOTD": '376',
    "RPL_YOUREOPER": '381',
    "RPL_REHASHING": '382',
    "RPL_YOURESERVICE": '383',
    "RPL_TIME": '391',
    "RPL_USERSSTART": '392',
    "RPL_USERS": '393',
    "RPL_ENDOFUSERS": '394',
    "RPL_NOUSERS": '395',
    "RPL_TRACELINK": '200',
    "RPL_TRACECONNECTING": '201',
    "RPL_TRACEHANDSHAKE": '202',
    "RPL_TRACEUNKNOWN": '203',
    "RPL_TRACEOPERATOR": '204',
    "RPL_TRACEUSER": '205',
    "RPL_TRACESERVER": '206',
    "RPL_TRACESERVICE": '207',
    "RPL_TRACENEWTYPE": '208',
    "RPL_TRACECLASS": '209',
    "RPL_TRACERECONNECT": '210',
    "RPL_TRACELOG": '261',
    "RPL_TRACEEND": '262',
    "RPL_STATSLINKINFO": '211',
    "RPL_STATSCOMMANDS": '212',
    "RPL_ENDOFSTATS": '219',
    "RPL_STATSUPTIME": '242',
    "RPL_STATSOLINE": '243',
    "RPL_UMODEIS": '221',
    "RPL_SERVLIST": '234',
    "RPL_SERVLISTEND": '235',
    "RPL_LUSERCLIENT": '251',
    "RPL_LUSEROP": '252',
    "RPL_LUSERUNKNOWN": '253',
    "RPL_LUSERCHANNELS": '254',
    "RPL_LUSERME": '255',
    "RPL_ADMINME": '256',
    "RPL_ADMINLOC": '257',
    "RPL_ADMINLOC": '258',
    "RPL_ADMINEMAIL": '259',
    "RPL_TRYAGAIN": '263',
    "ERR_NOSUCHNICK": '401',
    "ERR_NOSUCHSERVER": '402',
    "ERR_NOSUCHCHANNEL": '403',
    "ERR_CANNOTSENDTOCHAN": '404',
    "ERR_TOOMANYCHANNELS": '405',
    "ERR_WASNOSUCHNICK": '406',
    "ERR_TOOMANYTARGETS": '407',
    "ERR_NOSUCHSERVICE": '408',
    "ERR_NOORIGIN": '409',
    "ERR_NORECIPIENT": '411',
    "ERR_NOTEXTTOSEND": '412',
    "ERR_NOTOPLEVEL": '413',
    "ERR_WILDTOPLEVEL": '414',
    "ERR_BADMASK": '415',
    "ERR_UNKNOWNCOMMAND": '421',
    "ERR_NOMOTD": '422',
    "ERR_NOADMININFO": '423',
    "ERR_FILEERROR": '424',
    "ERR_NONICKNAMEGIVEN": '431',
    "ERR_ERRONEUSNICKNAME": '432',
    "ERR_NICKNAMEINUSE": '433',
    "ERR_NICKCOLLISION": '436',
    "ERR_UNAVAILRESOURCE": '437',
    "ERR_USERNOTINCHANNEL": '441',
    "ERR_NOTONCHANNEL": '442',
    "ERR_USERONCHANNEL": '443',
    "ERR_NOLOGIN": '444',
    "ERR_SUMMONDISABLED": '445',
    "ERR_USERSDISABLED": '446',
    "ERR_NOTREGISTERED": '451',
    "ERR_NEEDMOREPARAMS": '461',
    "ERR_ALREADYREGISTRED": '462',
    "ERR_NOPERMFORHOST": '463',
    "ERR_PASSWDMISMATCH": '464',
    "ERR_YOUREBANNEDCREEP": '465',
    "ERR_YOUWILLBEBANNED": '466',
    "ERR_KEYSET": '467',
    "ERR_CHANNELISFULL": '471',
    "ERR_UNKNOWNMODE": '472',
    "ERR_INVITEONLYCHAN": '473',
    "ERR_BANNEDFROMCHAN": '474',
    "ERR_BADCHANNELKEY": '475',
    "ERR_BADCHANMASK": '476',
    "ERR_NOCHANMODES": '477',
    "ERR_BANLISTFULL": '478',
    "ERR_NOPRIVILEGES": '481',
    "ERR_CHANOPRIVSNEEDED": '482',
    "ERR_CANTKILLSERVER": '483',
    "ERR_RESTRICTED": '484',
    "ERR_UNIQOPPRIVSNEEDED": '485',
    "ERR_NOOPERHOST": '491',
    "ERR_NOSERVICEHOST": '492',
    "ERR_UMODEUNKNOWNFLAG": '501',
    "ERR_USERSDONTMATCH": '502',
}

numeric_to_symbolic = {}
for k, v in symbolic_to_numeric.items():
    numeric_to_symbolic[v] = k
