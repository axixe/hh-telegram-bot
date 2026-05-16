# Project goal

Build a Telegram control panel for hh-applicant-tool.

The Telegram bot must not reimplement the business logic of hh-applicant-tool.
It only controls hh-applicant-tool as an external process/container and provides a simple Telegram UI.

# Product ideology

The bot is not a command-line interface inside Telegram.
The bot should behave like a small control panel with Telegram reply/inline keyboards.

Users should not need to type commands except `/start`.

# Stack

- Python
- aiogram
- Docker Compose
- python-dotenv
- subprocess with safe argument lists
- No shell=True

# Security rules

- Never allow arbitrary shell commands from Telegram.
- Only whitelisted Telegram user IDs may use the bot.
- Read allowed Telegram IDs from `TELEGRAM_ALLOWED_USER_IDS`.
- Read bot token from `TELEGRAM_BOT_TOKEN`.
- Never print secrets, tokens, SMS codes, or phone numbers in logs.
- Store secrets only in `.env`.
- Do not expose internal paths or raw stack traces to Telegram users.

# hh-applicant-tool integration

hh-applicant-tool is the source of truth for all HH logic.

The bot must only:

- start predefined hh-applicant-tool flows;
- stop the running process/container;
- check status;
- request logs later, when this feature is added.

Do not duplicate HH API logic inside the Telegram bot.

# Authorization flow

After `/start`, the bot must ask the user to authorize in HH.

Authorization must be done only through phone number and SMS code.
Do not implement login/password authorization.

Expected flow:

1. User sends `/start`.
2. Bot checks Telegram user access.
3. Bot greets the user.
4. Bot asks the user to authorize via phone number.
5. Bot asks for a phone number.
6. Bot starts hh-applicant-tool authorization flow using the provided phone number.
7. Bot asks the user to enter the SMS code received from HH.
8. Bot passes the SMS code to hh-applicant-tool.
9. Bot saves/uses the resulting hh-applicant-tool profile/session.
10. Bot shows the main keyboard.

If the current hh-applicant-tool CLI requires interactive input, implement a service wrapper that can run this process safely and pass phone/SMS input via stdin.

If fully automated SMS authorization is not possible with the current hh-applicant-tool CLI, implement the Telegram FSM/state flow and isolate the TODO in a dedicated `AuthService`.

# Main keyboard

The bot must use Telegram buttons, not text commands.

For now the main keyboard has only one dynamic action button:

- `▶️ Запустить`
- `⏹ Остановить`

The button text depends on current application status.

If hh-applicant-tool is not running, show:

- `▶️ Запустить`

If hh-applicant-tool is running, show:

- `⏹ Остановить`

# Start/stop behavior

`▶️ Запустить` should start the main automation flow:

- auto apply to vacancies;
- update/resume bumping.

This can initially be implemented as a predefined command runner action.

`⏹ Остановить` should stop the currently running automation process/container.

Do not allow multiple parallel runs for the same profile.
If the app is already running, show the stop button instead of starting another process.

# MVP scope

Implement only:

- `/start`
- access control by Telegram user ID
- phone/SMS authorization flow skeleton
- main keyboard
- dynamic start/stop button
- start automation action
- stop automation action
- status detection needed for dynamic button text

Do not implement yet:

- logs screen
- AI features
- multi-account UI
- settings UI
- cron/schedules
- vacancy filters
- statistics
- web dashboard

# Project structure

```text
bot/
  main.py
  config.py
  keyboards.py
  states.py
  services/
    command_runner.py
    auth_service.py
    app_status_service.py
```

# Code style

- Keep functions small.
- Add type hints.
- Use clear service classes.
- Keep Telegram handlers thin.
- Put business/process control logic into services.
- Use readable Russian texts for Telegram messages.
- Avoid overengineering, but keep the architecture extensible.

# User-facing language

All Telegram messages should be in Russian.

Tone:

- simple;
- clear;
- not too formal.

# Important implementation notes

The first implementation can be imperfect, but it must be safe.

Prefer explicit TODO comments in isolated services over spreading incomplete authorization logic across handlers.

If hh-applicant-tool does not expose a clean non-interactive authorization API, create a wrapper around its CLI and document the limitation in README.
