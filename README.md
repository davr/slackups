# pickups

Slack gateway for Google Hangouts using
[hangups](https://github.com/tdryer/hangups).

## Usage

`$ python3 run.py`

You will be given a URL to your oauth2 token.  Go to the url.  Copy the token.
You will be prompted for your oauth2 token.  Paste it in.
You will be prompted for your slack token, you can generate it from 
[this url](https://api.slack.com/docs/oauth-test-tokens#test_token_generator)

### Run under python3 and virtualenv

virtualenv -p python3 venv

source venv/bin/activate

pip install -r requirements.txt

mkdir -p ${HOME}/.cache/hangups/

python3 run.py

### Run under virtualenv, run hangups with zdaemon, run server on port 7667

virtualenv -p python3 venv

source venv/bin/activate

pip install -r requirements.txt

mkdir -p ${HOME}/.cache/hangups/

zdaemon -f -p 'python3 run.py --port 7667' start
