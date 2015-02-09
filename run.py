import logging
import os
import sys

import appdirs
import hangups.auth

from pickups.server import Server

def runit():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    logging.getLogger('hangups').setLevel(logging.WARNING)
    dirs = appdirs.AppDirs('hangups', 'hangups')
    default_cookies_path = os.path.join(dirs.user_cache_dir, 'cookies.json')
    cookies = hangups.auth.get_auth_stdin(default_cookies_path)
    Server(cookies=cookies).run('0.0.0.0', 16767)

if __name__ == '__main__':
    runit()
