# pickups

IRC gateway for Google Hangouts using
[hangups](https://github.com/tdryer/hangups).

This is currently just a prototype.


## Usage

`$ python3 run.py`

You will be prompted for your Google credentials and only the resulting cookies
from authentication will be saved. Then connect your IRC client to `localhost`
on port `6667`.

### Run under python3 and virtualenv

$ virtualenv -p python3 venv

$ source venv/bin/activate

$ pip install -r requirements.txt

$ mkdir -p ${HOME}/.cache/hangups/

$ python -m pickups
