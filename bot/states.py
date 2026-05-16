from aiogram.fsm.state import State, StatesGroup


class AuthStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_captcha = State()
    waiting_for_sms_code = State()


class CoverLetterStates(StatesGroup):
    waiting_for_text = State()
