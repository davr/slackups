"""Utility functions."""

from hangups.ui.utils import get_conv_name
import hashlib
import re
import string

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

    hashes[name] = conv_hash

    return name


def channel_to_conversation(channel, conv_list):
    """Return hangups.Conversation for channel name."""
    conv_hash = hashes[channel]
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
