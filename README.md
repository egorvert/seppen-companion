# Seppen-Companion
An advanced companion that lives right in your telegram chats

## Getting started
Create and activate virtual environment
```
python -m venv .venv
source .venv/bin/activate
```

Install requirements
```
cd agents
pip install -r requirements.txt
```

Setup up environment variables, you will need to create your own API keys for OpenAI, Mem0 and Telegram Bot Token 
> (note: Mem0 and Telegram bots are free, OpenAI will need like $5 API credits which will last you a while with this project)
```
.env
OPENAI_API_KEY=
MEM0_API_KEY=
TELEGRAM_BOT_TOKEN=
```

### Telegram setup

You will also need to create a bot using BotFather inside telegram and obtain the token

https://core.telegram.org/bots/tutorial#obtain-your-bot-token

### Creating a personality for your bot
You can create a custom personality following the json schema using the following tool (for free): https://seppen.ai/hiro/createpersonalityfictional-1

Copy the JSON output and put it in a new file in agents/personalities

## Running the bot
To start the bot, simply run the telegram_bot.py file (make sure you have your virtual environment active)
```
cd agents/src
python telegram_bot.py
```

You can now message the bot through telegram. Simply use the telegram search bar to search for your bot and run the start command.
