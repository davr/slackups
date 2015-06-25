"""Utility functions."""

from hangups.ui.utils import get_conv_name
import hashlib
import re
import string
import unicodedata

CONV_HASH_LEN = 7

hashes = {}

def conversation_to_channel(conv):
    """Return channel name for hangups.Conversation."""
    # Must be 50 characters max and not contain space or comma.
    conv_hash = hashlib.sha1(conv.id_.encode()).hexdigest()

    # comma to underscore
    # space to nospace
    name = get_conv_name(conv).replace(',', '_').replace(' ', '')

    # only keep alpha nums
    name = re.sub(r'[^0-9a-zA-Z_]+', '', name)

    name = "#{}".format(name[:49])

    if name in hashes and hashes[name] != conv_hash:
        while name in hashes:
            if len(name) > 50:
                name = "{}_".format(name[:-1])
            else:
                name = "{}_".format(name)

    hashes[name.lower()] = conv_hash

    return name


def channel_to_conversation(channel, conv_list):
    """Return hangups.Conversation for channel name."""
    conv_hash = hashes[channel.lower()]
    return {hashlib.sha1(conv.id_.encode()).hexdigest(): conv
            for conv in conv_list.get_all()}[conv_hash]


def get_nick(user):
    """Return nickname for a hangups.User."""
    return get_name(user)
    # Remove disallowed characters and limit to max length 15
    fname = user.full_name.split()
    name = fname[0]
    if len(fname) > 1:
    	name += fname[1][:1]
    name = name.split("@")[0]
    return re.sub(r'[^\w\[\]\{\}\^`|_\\-]', '', name)[:15]

def get_name(user):
    """Return nickname for a hangups.User."""
    # Remove disallowed characters and limit to max length 15
    return re.sub(r'[^\w\[\]\{\}\^`|_\\-]', '', user.full_name)[:15]

def get_hostmask(user):
    """Return hostmask for a hangups.User."""
    return '{}!{}@hangouts'.format(get_nick(user), user.id_.chat_id)


def get_topic(conv):
    """Return IRC topic for a conversation."""
    return 'Hangouts conversation: {}'.format(get_conv_name(conv))


SMILEYS = {chr(k): v for k, v in {
        0x263a: ':)',
        0x1f494: '</3',
        0x1f49c: '<3',
        0x1f60a: '=D',
        0x1f600: ':D',
        0x1f601: '^_^',
        0x1f602: ':\'D',
        0x1f603: ':D',
        0x1f604: ':D',
        0x1f605: ':D',
        0x1f606: ':D',
        0x1f607: '0:)',
        0x1f608: '}:)',
        0x1f609: ';)',
        0x1f60e: '8)',
        0x1f610: ':|',
        0x1f611: '-_-',
        0x1f613: 'o_o',
        0x1f614: 'u_u',
        0x1f615: ':/',
        0x1f616: ':s',
        0x1f617: ':*',
        0x1f618: ';*',
        0x1f61B: ':P',
        0x1f61C: ';P',
        0x1f61E: ':(',
        0x1f621: '>:(',
        0x1f622: ';_;',
        0x1f623: '>_<',
        0x1f626: 'D:',
        0x1f62E: ':o',
        0x1f632: ':O',
        0x1f635: 'x_x',
        0x1f638: ':3',
}.items()}

def smileys_to_ascii(s):
    res = []
    for i, c in enumerate(s):
        if c in SMILEYS:
            res.append(SMILEYS[c])
            if i < len(s) - 1 and s[i + 1] in SMILEYS: # separate smileys
                res.append(' ')
        elif ord(c) >= 0x2702 and ord(c) <= 0x1f6ff:
            try:
                name = unicodedata.name(c)
                res.append((':'+name+':').lower())
            except:
                res.append(c)
        else:
            res.append(c)
    return ''.join(res)
