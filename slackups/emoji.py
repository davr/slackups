import json
import re
import unicodedata
import string
import hashlib

def smileys_to_ascii(s):
    res = []
    for i, c in enumerate(s):
        if c in SMILEYS:
            res.append(SMILEYS[c])
            if i < len(s) - 1 and s[i + 1] in SMILEYS: # separate smileys
                res.append(' ')
        elif ord(c) > 128 and unicodedata.category(c)[0] == 'S':
            try:
                name = ':'+unicodedata.name(c).lower().replace(' ','-')+':'
                res.append(name)
            except:
                res.append(c)
        else:
            res.append(c)
    return ''.join(res)

def ascii_to_smileys(s):
    res = []
    words = s.split(' ')
    for word in words:
        if word in ASCIIS:
            res.append(ASCIIS[word])
        elif word[0]==':' and word[-1]==':':
            try:
                emoji = unicodedata.lookup(word[1:-1].upper().replace('-',' '))
                res.append(emoji)
            except:
                res.append(word)
        else:
            res.append(word)
    return ''.join(res)

def emoji_to_shortcode(message):
    res = []
    for i, c in enumerate(message):
        if ord(c) > 128 and unicodedata.category(c)[0] == 'S':
            name = ':'+unicodedata.name(c).lower().replace(' ','-')+':'
            res.append(name)
        else:
            res.append(c)
    return ''.join(res)



def shortcode_to_emoji(message):
    parts = message.split(":")
    out = ""
    c = False
    for part in parts:
        if part in name_to_emoji:
            out += name_to_emoji[part]
            c = False
        else:
            if c:
                out += ':'
            else:
                c = True
            out += part
    return out

with open('emoji/gemoji.js', 'rb') as fp:
    data = fp.read()
    data = data.decode('utf-8')
    gemoji = json.loads(data)

name_to_emoji = {}

for emoji, data in gemoji.items():
    for name in data['names']:
        name_to_emoji[name] = emoji




SMILEYS = {chr(k): v for k, v in {
        0x263a: ':)',
        0x1f494: '</3',
        0x1f49c: '<3',
        0x2764: '<3',
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
        0x1f620: '>:(',
        0x1f62c: '>:(',
        0x1f62a: '(-_-)zzz',
        0x1f634: '(-_-).zZ',
        0x1f4a4: '.zZ',
        0x1f624: '>:(',
        0x1f625: 'D:',
        0x1f627: 'D:',
        0x1f619: ':*',
        0x1f61a: ':*',
        0x1f612: ':|',
        0x1f636: ':|',
        0x1f613: ':O',
        0x1f630: ':O',
        0x1f628: 'o_o',
        0x1f631: 'O_O', 
        0x1f62d: ':''(', 
        0x1f61d: ';P',
        0x1f64d: '>:|', 
        0x1f626: '>:O',
        0x1f61f: ':/',
        0x2639: ':(',
        0x1f60b: ';P',
        0x1f60d: '<3<3<3',
        0x1f642: ':)',
        0x1f917: ':hug:',
        0x1f914: ':/ hmm',
        0x1f644: '(e_e)',
        0x1f62f: ':-o',
        0x1f62b: "'>_<",
        0x1f913: 'B-)',
        0x1f641: ':(',
        0x1f629: '>_<',

}.items()}

ASCIIS = {v: chr(k) for k, v in {
        0x1f62a: '(-_-)zzz',
        0x1f634: '(-_-).zZ',
        0x1f4a4: '.zZ',
        0x1f631: 'O_O', 
        0x1f62d: ":''(", 
        0x1f64d: '>:|', 
        0x1f626: '>:O',
        0x2764: ':heart:',
        0x263a: ':)',
        0x1f494: '</3',
        0x1f49c: '<3',
        0x1f60a: '=D',
        0x1f600: ':D',
        0x1f601: '^_^',
        0x1f602: ':\'D',
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
        0x1f61e: ':(',
        0x1f621: '>:(',
        0x1f622: ';_;',
        0x1f622: ';(',
        0x1f622: ":'(",
        0x1f623: '>_<',
        0x1f626: 'D:',
        0x1f62E: ':o',
        0x1f632: ':O',
        0x1f635: 'x_x',
        0x1f638: ':3',
        0x1f917: ':hug:',
        0x1f644: '(e_e)',
}.items()}
