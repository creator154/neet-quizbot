"""Telegram poll_answer update handler with idempotency and score evaluation."""

from telegram import Update
from telegram.ext import ContextTypes

from app.database.connection import get_db
from app.database.repositories.attempt_repo import AttemptRepository
from app.services.attempt_service import AttemptService
from app.bot.handlers.quiz_handlers import (
    send_quiz_results
)
from app.utils.logger import logger


async def handle_poll_answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle participant poll answer.

    The answer is recorded immediately, but the next question is NOT
    sent immediately. The existing server-side timer remains active
    and will trigger the next question when the full poll duration
    has expired.
    """

    poll_answer = update.poll_answer

    if not poll_answer or not poll_answer.user:
        return

    # Ignore retracted answers
    if not poll_answer.option_ids:
        return

    poll_id = poll_answer.poll_id
    user_id = poll_answer.user.id
    selected_option_index = poll_answer.option_ids[0]

    with get_db() as db:

        # Handle group quiz answers separately
        from app.services.group_quiz_service import GroupQuizService

        handled_group = (
            GroupQuizService.record_participant_answer(
                db=db,
                poll_id=poll_id,
                user_id=user_id,
                username=poll_answer.user.username,
                first_name=poll_answer.user.first_name,
                selected_option=selected_option_index
            )
        )

        if handled_group:
            return

        # Find the question belonging to this poll
        aq = AttemptRepository.get_attempt_question_by_poll_id(
            db,
            poll_id
        )

        if not aq:
            return

        attempt_id = aq.attempt_id
        attempt_question_id = aq.id

        # IMPORTANT:
        # Do NOT cancel the timer here.
        #
        # The timer must remain active until the poll's
        # complete duration has elapsed.
        #
        # TimerService.cancel_question_timeout(...)
        # is intentionally NOT called.

        answer, is_complete, attempt = (
            AttemptService.handle_poll_answer(
                db=db,
                poll_id=poll_id,
                telegram_user_id=user_id,
                selected_option_index=selected_option_index
            )
        )

    if not answer or not attempt:
        return

    # IMPORTANT:
    # Do NOT send the next question here.
    #
    # The scheduled timeout job in quiz_handlers.py will fire
    # after the complete timer duration and then call
    # send_next_question().
    #
    # This prevents a new poll from appearing early.

    logger.info(
        "Answer recorded. Waiting for timer completion. "
        f"attempt_id={attempt_id}, "
        f"attempt_question_id={attempt_question_id}, "
        f"user_id={user_id}"
    )

    return
