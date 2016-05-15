"""Utility functions."""

from hangups.ui.utils import get_conv_name
import hashlib
import re
import string
import unicodedata
from . import emoji

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

    if name == "":
        name = emoji.emoji_to_shortcode(get_conv_name(conv))
        name = re.sub(r'[^0-9a-zA-Z_]+', '', name)

    name = "{}".format(name[:21])

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
    name = user.full_name
    try:
        if name == 'Unknown':
            if (user.first_name == 'Unknown' or user.firt_name == '') and len(user.emails) > 0:
                name = user.emails[0]
            else:
                if not hasattr(user,'last_name') or user.last_name == 'Unknown' or user.last_name == '':
                    name = user.first_name
                else:
                    name = user.first_name+user.last_name
    except:
        pass
    
    return re.sub(r'[^\w\[\]\{\}\^`|_\\-]', '', name)[:15]

def get_hostmask(user):
    """Return hostmask for a hangups.User."""
    return '{}!{}@hangouts'.format(get_nick(user), user.id_.chat_id)


def get_topic(conv):
    """Return IRC topic for a conversation."""
    return get_conv_name(conv)


