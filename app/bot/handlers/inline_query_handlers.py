"""Inline query handler for rich quiz sharing via @bot_name."""

import hashlib

from telegram import (
    Update,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
)
from telegram.ext import ContextTypes

from app.config import settings
from app.database.connection import get_db
from app.database.repositories.quiz_repo import QuizRepository
from app.utils.logger import logger


async def handle_inline_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle inline queries like @bot_username quiz:CODE or search query."""

    inline_query = update.inline_query

    if not inline_query:
        return

    try:
        raw_query = (inline_query.query or "").strip()

        # Get bot username
        bot_user = await context.bot.get_me()

        clean_bot = (
            bot_user.username
            or settings.BOT_USERNAME
            or "akaxxh_bot"
        ).lstrip("@")

        # ---------------------------------------------------------
        # Extract quiz code
        # Supports:
        # quiz:ABC123
        # quiz_ABC123
        # ABC123
        # ---------------------------------------------------------
        quiz_code = raw_query

        if raw_query.startswith("quiz:"):
            quiz_code = raw_query.replace("quiz:", "", 1).strip()

        elif raw_query.startswith("quiz_"):
            quiz_code = raw_query.replace("quiz_", "", 1).strip()

        results = []

        with get_db() as db:

            quizzes = []

            # -----------------------------------------------------
            # First: Search exact quiz code
            # -----------------------------------------------------
            if quiz_code:

                q = QuizRepository.get_by_code(
                    db,
                    quiz_code
                )

                if q and q.status == "PUBLISHED":
                    quizzes.append(q)

            # -----------------------------------------------------
            # If exact code not found:
            # Search user's published quizzes
            # -----------------------------------------------------
            if not quizzes:

                user_id = inline_query.from_user.id

                from app.database.repositories.user_repo import (
                    UserRepository
                )

                user = UserRepository.get_by_telegram_id(
                    db,
                    user_id
                )

                if user:

                    user_quizzes = QuizRepository.get_by_creator(
                        db,
                        user.id
                    )

                    published = [
                        item
                        for item in user_quizzes
                        if item.status == "PUBLISHED"
                    ]

                    # Search by title
                    if raw_query:

                        search_text = raw_query.lower()

                        quizzes = [
                            item
                            for item in published
                            if search_text in (item.title or "").lower()
                        ][:10]

                    else:

                        quizzes = published[:10]

            # -----------------------------------------------------
            # Build inline results
            # -----------------------------------------------------
            for quiz in quizzes:

                # Question count
                q_count = len(quiz.questions)

                # Timer
                timer_seconds = quiz.timer_seconds or 0

                if timer_seconds > 0:
                    timer_text = f"{timer_seconds} sec"
                else:
                    timer_text = "No Timer"

                # Description
                desc_text = ""

                if quiz.description:
                    desc_text = f"{quiz.description}\n\n"

                # Attempts
                attempts_count = len(quiz.attempts)

                if attempts_count > 0:
                    answered_str = (
                        f" {attempts_count} people answered"
                    )
                else:
                    answered_str = ""

                # -------------------------------------------------
                # Promo keyboard
                # -------------------------------------------------
                from app.utils.branding import (
                    get_promo_keyboard_row
                )

                # -------------------------------------------------
                # IMPORTANT:
                # No Markdown / HTML parsing here.
                #
                # This prevents decorative characters such as:
                # *, _, [, ], (, ), etc.
                # from breaking Telegram inline results.
                # -------------------------------------------------
                message_text = (
                    f"🎲 Quiz '{quiz.title}'{answered_str}\n\n"
                    f"{desc_text}"
                    f"🖊 {q_count} questions · ⏱ {timer_text}"
                )

                # -------------------------------------------------
                # Keyboard
                # -------------------------------------------------
                keyboard = [

                    [
                        InlineKeyboardButton(
                            "Start this quiz",
                            url=(
                                f"https://t.me/{clean_bot}"
                                f"?start=quiz_{quiz.quiz_code}"
                            )
                        )
                    ],

                    [
                        InlineKeyboardButton(
                            "Start quiz in group",
                            url=(
                                f"https://t.me/{clean_bot}"
                                f"?startgroup=quiz_{quiz.quiz_code}"
                            )
                        )
                    ],

                    [
                        InlineKeyboardButton(
                            "Share quiz",
                            switch_inline_query=(
                                f"quiz:{quiz.quiz_code}"
                            )
                        )
                    ],

                    get_promo_keyboard_row(),
                ]

                # -------------------------------------------------
                # Unique result ID
                # -------------------------------------------------
                result_id = hashlib.md5(
                    f"{quiz.quiz_code}_{quiz.id}".encode()
                ).hexdigest()

                # -------------------------------------------------
                # Inline result
                # -------------------------------------------------
                results.append(
                    InlineQueryResultArticle(
                        id=result_id,

                        # Keep title reasonably short so very long
                        # decorative quiz names don't cause problems.
                        title=f"Quiz '{(quiz.title or 'Untitled')[:100]}'",

                        description=(
                            f"{q_count} questions · "
                            f"{timer_text}"
                        ),

                        input_message_content=(
                            InputTextMessageContent(
                                message_text=message_text,

                                # IMPORTANT:
                                # No parse_mode here.
                                # Raw text is sent safely.
                                link_preview_options=(
                                    LinkPreviewOptions(
                                        is_disabled=True
                                    )
                                ),
                            )
                        ),

                        reply_markup=InlineKeyboardMarkup(
                            keyboard
                        ),
                    )
                )

        # ---------------------------------------------------------
        # Answer inline query
        # ---------------------------------------------------------
        await inline_query.answer(
            results,
            cache_time=1,
            is_personal=True
        )

    except Exception as e:

        logger.exception(
            f"Error handling inline query: {e}"
        )

        # Try to return an empty result instead of crashing
        try:
            await inline_query.answer(
                [],
                cache_time=1,
                is_personal=True
            )
        except Exception:
            logger.exception(
                "Failed to answer inline query after error."
            )
