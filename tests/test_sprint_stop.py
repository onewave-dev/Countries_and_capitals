import asyncio
from types import SimpleNamespace

from bot.handlers_sprint import cb_sprint
from bot.state import SprintSession
from bot.handlers_menu import WELCOME, main_menu_kb


class DummyJob:
    def __init__(self):
        self.removed = False
        self.ran = False

    def schedule_removal(self):
        self.removed = True

    def run(self):
        if not self.removed:
            self.ran = True


class DummyQuery:
    def __init__(self):
        self.data = "sprint:stop"
        self.message = SimpleNamespace(chat_id=1)
        self.answered = False
        self.edited: list[tuple[str, object]] = []

    async def answer(self):
        self.answered = True

    async def edit_message_text(self, text, reply_markup=None):
        self.edited.append((text, reply_markup))


def test_sprint_stop_cancels_timer_and_returns_to_menu():
    job = DummyJob()
    session = SprintSession(user_id=1, duration_sec=60)
    context = SimpleNamespace(user_data={"sprint_session": session, "sprint_job": job})
    q = DummyQuery()
    update = SimpleNamespace(callback_query=q, effective_user=SimpleNamespace(id=1))

    asyncio.run(cb_sprint(update, context))

    assert q.answered, "Callback was not answered"
    assert job.removed, "Timer job was not cancelled"
    assert "sprint_session" not in context.user_data
    assert "sprint_job" not in context.user_data
    assert q.edited, "Main menu was not shown"
    text, markup = q.edited[0]
    assert text == WELCOME
    assert markup.inline_keyboard == main_menu_kb().inline_keyboard
    job.run()
    assert not job.ran, "Timer job ran after being cancelled"
