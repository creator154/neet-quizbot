"""Inline callback query handlers."""

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.database.connection import get_db
from app.database.repositories.quiz_repo import QuizRepository
from app.services.quiz_service import QuizService
from app.services.attempt_service import AttemptService

from app.bot.keyboards.inline import (
    get_shuffle_keyboard,
    get_quiz_result_keyboard,
    get_quiz_intro_keyboard,
    get_quiz_created_keyboard,
    get_group_ready_keyboard,
)

from app.bot.keyboards.reply import get_remove_keyboard
from app.bot.handlers.quiz_handlers import send_next_question
from app.utils.localization import t
from app.utils.logger import logger


async def handle_callback_query(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Route inline keyboard callback queries."""

    query = update.callback_query

    if not query or not query.data:
        return

    data = query.data

    # =========================================================
    # OLD DEVELOPER CALLBACK
    # =========================================================

    if data == "open_developer":
        try:
            await query.answer(
                "Please use the Developer button."
            )
        except Exception:
            pass
        return

    # =========================================================
    # OLD SUPPORT CALLBACK
    # =========================================================

    if data == "open_support":
        try:
            await query.answer(
                "Please use the Support button."
            )
        except Exception:
            pass
        return

    # =========================================================
    # NORMAL CALLBACK ANSWER
    # =========================================================

    try:
        await query.answer()
    except Exception:
        pass

    user = update.effective_user
    chat = update.effective_chat

    if not user or not chat:
        return

    try:
        bot_user = await context.bot.get_me()
        bot_username = bot_user.username or "quizbot"
    except Exception:
        bot_username = "quizbot"

    # =========================================================
    # 1. MENU SHORTCUTS
    # =========================================================

    if data == "cmd:newquiz":

        with get_db() as db:
            quiz, status = QuizService.start_new_quiz(
                db,
                user.id,
                user.username,
                user.first_name
            )

            if status == "UNFINISHED_EXISTS":
                await chat.send_message(
                    t("newquiz_unfinished")
                )
                return

        await chat.send_message(
            t("newquiz_prompt_title"),
            reply_markup=get_remove_keyboard()
        )
        return

    elif data == "cmd:quizzes":

        from app.bot.handlers.commands import quizzes_command

        await quizzes_command(update, context)
        return

    elif data == "cmd:help":

        from app.bot.handlers.commands import help_command

        await help_command(update, context)
        return

    elif data == "cmd:start":

        from app.bot.handlers.commands import start_command

        await start_command(update, context)
        return

    # =========================================================
    # 2. TIMER SELECTION
    # =========================================================

    elif data.startswith("timer:"):

        try:
            seconds = int(data.split(":", 1)[1])
        except (ValueError, IndexError):
            return

        with get_db() as db:
            QuizService.set_timer(
                db,
                user.id,
                seconds
            )

        timer_display = (
            f"{seconds} seconds"
            if seconds > 0
            else "No Timer"
        )

        try:
            await query.edit_message_text(
                text=(
                    f"⏱ Question timer set to: "
                    f"*{timer_display}*\n\n"
                    f"{t('shuffle_prompt')}"
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_shuffle_keyboard()
            )
        except Exception:
            pass

        return

    # =========================================================
    # 3. SHUFFLE SELECTION
    # =========================================================

    elif data.startswith("shuffle:"):

        mode = data.split(":", 1)[1]

        shuffle_q = mode in ("all", "questions")
        shuffle_opt = mode in ("all", "options")

        with get_db() as db:
            QuizService.set_shuffle(
                db,
                user.id,
                shuffle_q,
                shuffle_opt
            )

        from app.bot.keyboards.inline import get_marking_keyboard

        try:
            await query.edit_message_text(
                text=(
                    "⚖️ *Choose the marking scheme for this quiz:*\n\n"
                    "• *🎯 NEET Marking*: "
                    "+4 Correct, -1 Wrong, 0 Skipped\n"
                    "• *🏥 NORCET Marking*: "
                    "+1 Correct, -0.33 Wrong, 0 Skipped\n"
                    "• *✅ Simple Marking*: "
                    "+1 Correct, 0 Wrong, 0 Skipped"
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_marking_keyboard()
            )
        except Exception:
            pass

        return

    # =========================================================
    # 3B. MARKING SELECTION & PUBLISHING
    # =========================================================

    elif data.startswith("marking:"):

        parts = data.split(":")

        if len(parts) < 3:
            return

        try:
            correct = float(parts[1])
            wrong = float(parts[2])
        except ValueError:
            return

        with get_db() as db:

            QuizService.set_marking(
                db,
                user.id,
                correct,
                wrong,
                0.0
            )

            quiz = QuizService.publish_draft(
                db,
                user.id
            )

            if not quiz:

                from app.database.repositories.user_repo import (
                    UserRepository
                )

                user_obj = UserRepository.get_by_telegram_id(
                    db,
                    user.id
                )

                if user_obj:

                    quizzes = QuizRepository.get_by_creator(
                        db,
                        user_obj.id
                    )

                    if quizzes and quizzes[0].status == "PUBLISHED":
                        quiz = quizzes[0]

            if not quiz:

                await chat.send_message(
                    "⚠️ Could not publish quiz. Please try again."
                )
                return

        try:
            await query.message.delete()
        except Exception:
            pass

        from app.bot.handlers.creation_handlers import (
            send_published_quiz_summary
        )

        await send_published_quiz_summary(
            chat,
            quiz,
            bot_username
        )

        return

    # =========================================================
    # 3C. EDIT QUIZ MENU
    # =========================================================

    elif data.startswith("edit_quiz:"):

        quiz_code = data.split(":", 1)[1].strip()

        logger.info(
            f"EDIT QUIZ CALLBACK: user={user.id}, quiz={quiz_code}"
        )

        from app.bot.keyboards.inline import (
            get_edit_quiz_keyboard
        )

        with get_db() as db:

            quiz = QuizRepository.get_by_code(
                db,
                quiz_code
            )

            if not quiz:
                await query.answer(
                    "Quiz not found.",
                    show_alert=True
                )

                logger.warning(
                    f"Edit failed: quiz not found: {quiz_code}"
                )

                return

            creator = quiz.creator

            if not creator or creator.telegram_id != user.id:

                await query.answer(
                    "You can only edit your own quizzes.",
                    show_alert=True
                )

                logger.warning(
                    f"Unauthorized edit attempt: "
                    f"user={user.id}, quiz={quiz_code}"
                )

                return

            quiz_title = quiz.title or "Untitled Quiz"

        # Plain text intentionally used here.
        # This prevents Markdown errors when the quiz title
        # contains *, _, [, ], (, ), or other special characters.
        edit_text = (
            "⚙️ Edit Quiz Settings\n\n"
            f"Quiz: {quiz_title}\n\n"
            "Select what you want to edit:"
        )

        try:

            await query.edit_message_text(
                text=edit_text,
                reply_markup=get_edit_quiz_keyboard(
                    quiz_code
                )
            )

            logger.info(
                f"Edit menu opened successfully: {quiz_code}"
            )

        except Exception as e:

            logger.exception(
                f"Failed to edit quiz menu "
                f"for {quiz_code}: {e}"
            )

            # Fallback if Telegram cannot edit the old message.
            try:

                await chat.send_message(
                    text=edit_text,
                    reply_markup=get_edit_quiz_keyboard(
                        quiz_code
                    )
                )

            except Exception as send_error:

                logger.exception(
                    f"Failed to send edit menu fallback: "
                    f"{send_error}"
                )

        return

    # =========================================================
    # 4. EDIT TITLE
    # =========================================================

    elif data.startswith("edit_title:"):

        quiz_code = data.split(":", 1)[1]

        context.user_data["editing_quiz_code"] = quiz_code
        context.user_data["editing_field"] = "title"

        await chat.send_message(
            "📝 *Please send the new title for your quiz:*",
            parse_mode=ParseMode.MARKDOWN
        )

        return

    # =========================================================
    # 5. EDIT DESCRIPTION
    # =========================================================

    elif data.startswith("edit_desc:"):

        quiz_code = data.split(":", 1)[1]

        context.user_data["editing_quiz_code"] = quiz_code
        context.user_data["editing_field"] = "desc"

        await chat.send_message(
            "📄 *Please send the new description for your quiz "
            "(or send /skip to remove description):*",
            parse_mode=ParseMode.MARKDOWN
        )

        return

    # =========================================================
    # 6. EDIT TIMER MENU
    # =========================================================

    elif data.startswith("edit_timer:"):

        quiz_code = data.split(":", 1)[1]

        from app.bot.keyboards.inline import (
            get_edit_timer_keyboard
        )

        try:
            await query.edit_message_text(
                text="⏱ *Select a new timer per question:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_edit_timer_keyboard(
                    quiz_code
                )
            )
        except Exception as e:
            logger.exception(
                f"Failed to open edit timer menu: {e}"
            )

        return

    # =========================================================
    # 7. EDIT TIMER
    # =========================================================

    elif data.startswith("ed_tm:"):

        parts = data.split(":")

        if len(parts) < 3:
            return

        quiz_code = parts[1]

        try:
            seconds = int(parts[2])
        except ValueError:
            return

        with get_db() as db:

            quiz = QuizRepository.get_by_code(
                db,
                quiz_code
            )

            if quiz and quiz.creator.telegram_id == user.id:

                quiz.timer_seconds = seconds

                db.commit()
                db.refresh(quiz)

                await query.answer(
                    f"Timer set to "
                    f"{seconds} seconds!"
                    if seconds > 0
                    else "Timer disabled!"
                )

                try:
                    await query.message.delete()
                except Exception:
                    pass

                from app.bot.handlers.creation_handlers import (
                    send_published_quiz_summary
                )

                await send_published_quiz_summary(
                    chat,
                    quiz,
                    bot_username
                )

        return

    # =========================================================
    # 8. EDIT SHUFFLE MENU
    # =========================================================

    elif data.startswith("edit_shuffle:"):

        quiz_code = data.split(":", 1)[1]

        from app.bot.keyboards.inline import (
            get_edit_shuffle_keyboard
        )

        try:
            await query.edit_message_text(
                text="🔀 *Select shuffle settings for this quiz:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_edit_shuffle_keyboard(
                    quiz_code
                )
            )
        except Exception as e:
            logger.exception(
                f"Failed to open edit shuffle menu: {e}"
            )

        return

    # =========================================================
    # 9. EDIT SHUFFLE
    # =========================================================

    elif data.startswith("ed_sh:"):

        parts = data.split(":")

        if len(parts) < 3:
            return

        quiz_code = parts[1]
        mode = parts[2]

        shuffle_q = mode in ("all", "questions")
        shuffle_opt = mode in ("all", "options")

        with get_db() as db:

            quiz = QuizRepository.get_by_code(
                db,
                quiz_code
            )

            if quiz and quiz.creator.telegram_id == user.id:

                quiz.shuffle_questions = shuffle_q
                quiz.shuffle_options = shuffle_opt

                db.commit()
                db.refresh(quiz)

                await query.answer(
                    "Shuffle settings updated!"
                )

                try:
                    await query.message.delete()
                except Exception:
                    pass

                from app.bot.handlers.creation_handlers import (
                    send_published_quiz_summary
                )

                await send_published_quiz_summary(
                    chat,
                    quiz,
                    bot_username
                )

        return

    # =========================================================
    # 10. EDIT MARKING MENU
    # =========================================================

    elif data.startswith("edit_marking:"):

        quiz_code = data.split(":", 1)[1]

        from app.bot.keyboards.inline import (
            get_edit_marking_keyboard
        )

        try:
            await query.edit_message_text(
                text=(
                    "⚖️ *Choose a new marking scheme for this quiz:*\n\n"
                    "• *🎯 NEET Marking*: "
                    "+4 Correct, -1 Wrong, 0 Skipped\n"
                    "• *🏥 NORCET Marking*: "
                    "+1 Correct, -0.33 Wrong, 0 Skipped\n"
                    "• *✅ Simple Marking*: "
                    "+1 Correct, 0 Wrong, 0 Skipped"
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_edit_marking_keyboard(
                    quiz_code
                )
            )
        except Exception as e:
            logger.exception(
                f"Failed to open edit marking menu: {e}"
            )

        return

    # =========================================================
    # 11. EDIT MARKING
    # =========================================================

    elif data.startswith("ed_mk:"):

        parts = data.split(":")

        if len(parts) < 4:
            return

        quiz_code = parts[1]

        try:
            correct = float(parts[2])
            wrong = float(parts[3])
        except ValueError:
            return

        with get_db() as db:

            quiz = QuizRepository.get_by_code(
                db,
                quiz_code
            )

            if quiz and quiz.creator.telegram_id == user.id:

                quiz.correct_marks = correct
                quiz.wrong_marks = wrong

                db.commit()
                db.refresh(quiz)

                await query.answer(
                    "Marking scheme updated!"
                )

                try:
                    await query.message.delete()
                except Exception:
                    pass

                from app.bot.handlers.creation_handlers import (
                    send_published_quiz_summary
                )

                await send_published_quiz_summary(
                    chat,
                    quiz,
                    bot_username
                )

        return

    # =========================================================
    # 12. DELETE QUIZ MENU
    # =========================================================

    elif data.startswith("del_quiz:"):

        quiz_code = data.split(":", 1)[1]

        from app.bot.keyboards.inline import (
            get_delete_confirm_keyboard
        )

        try:
            await query.edit_message_text(
                text=(
                    "⚠️ *Are you sure you want to delete this quiz?*\n"
                    "This action cannot be undone."
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_delete_confirm_keyboard(
                    quiz_code
                )
            )
        except Exception as e:
            logger.exception(
                f"Failed to open delete menu: {e}"
            )

        return

    # =========================================================
    # 13. DELETE CONFIRM
    # =========================================================

    elif data.startswith("del_confirm:"):

        quiz_code = data.split(":", 1)[1]

        with get_db() as db:

            quiz = QuizRepository.get_by_code(
                db,
                quiz_code
            )

            if quiz and quiz.creator.telegram_id == user.id:

                db.delete(quiz)
                db.commit()

                await query.edit_message_text(
                    "🗑 *Quiz has been deleted successfully.*",
                    parse_mode=ParseMode.MARKDOWN
                )

            else:

                await query.answer(
                    "Could not delete quiz.",
                    show_alert=True
                )

        return

    # =========================================================
    # 14. BACK TO QUIZ
    # =========================================================

    elif data.startswith("back_to_quiz:"):

        quiz_code = data.split(":", 1)[1]

        with get_db() as db:

            quiz = QuizRepository.get_by_code(
                db,
                quiz_code
            )

            if quiz:

                try:
                    await query.message.delete()
                except Exception:
                    pass

                from app.bot.handlers.creation_handlers import (
                    send_published_quiz_summary
                )

                await send_published_quiz_summary(
                    chat,
                    quiz,
                    bot_username
                )

        return

    # =========================================================
    # 15. START PRIVATE QUIZ ATTEMPT
    # =========================================================

    elif data.startswith("start_attempt:"):

        quiz_code = data.split(":", 1)[1]

        with get_db() as db:

            attempt, status = AttemptService.start_attempt(
                db=db,
                telegram_user_id=user.id,
                quiz_code=quiz_code,
                username=user.username,
                first_name=user.first_name
            )

        if status != "SUCCESS" or not attempt:

            await chat.send_message(
                "⚠️ Could not start quiz. "
                "It may have no questions or be unavailable."
            )
            return

        await chat.send_message(
            "🚀 Starting your quiz attempt! Get ready..."
        )

        await send_next_question(
            context,
            chat.id,
            user.id,
            attempt.id
        )

        return

    # =========================================================
    # 16. GROUP QUIZ
    # =========================================================

    elif (
        data.startswith("grp_ready:")
        or data.startswith("start_grp:")
    ):

        import asyncio

        from app.services.group_quiz_service import (
            GroupQuizService
        )

        from app.bot.handlers.group_quiz_handlers import (
            deliver_group_question
        )

        quiz_code = data.split(":", 1)[1]

        chat_data = context.chat_data

        ready_key = f"ready_{quiz_code}"
        countdown_key = f"countdown_{quiz_code}"

        ready_users = chat_data.setdefault(
            ready_key,
            set()
        )

        ready_users.add(user.id)

        ready_count = len(ready_users)

        # Update ready button count
        try:
            await query.edit_message_reply_markup(
                reply_markup=get_group_ready_keyboard(
                    quiz_code,
                    ready_count
                )
            )
        except Exception:
            pass

        # Countdown already started
        if chat_data.get(countdown_key):

            await query.answer(
                f"✋ You are ready! "
                f"({ready_count} participants ready)",
                show_alert=False
            )

            return

        # Start countdown
        chat_data[countdown_key] = True

        await query.answer(
            "✋ You are ready! Starting countdown...",
            show_alert=False
        )

        with get_db() as db:

            session, status = (
                GroupQuizService.get_or_create_session(
                    db,
                    quiz_code,
                    chat.id
                )
            )

            if status != "SUCCESS" or not session:

                chat_data[countdown_key] = False

                await chat.send_message(
                    "⚠️ Could not start group quiz. "
                    "It may have no questions or be unavailable."
                )

                return

            GroupQuizService.start_session(
                db,
                session.id
            )

            session_id = session.id

            quiz_obj = session.quiz

            quiz_title = (
                quiz_obj.title
                if quiz_obj
                else "Quiz"
            )

        # 3..2..1 Countdown
        for remaining in [3, 2, 1]:

            try:
                await query.edit_message_text(
                    text=(
                        f"🎲 *Get ready for the quiz: "
                        f"{quiz_title}*\n\n"
                        f"🚀 *{len(ready_users)} "
                        f"participant(s) ready!*\n\n"
                        f"⏱ *The quiz will begin "
                        f"in {remaining}...*"
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                pass

            await asyncio.sleep(1)

        try:

            await query.edit_message_text(
                text=(
                    f"🎲 *Quiz: {quiz_title}*\n\n"
                    "🚀 *Starting now! "
                    "Good luck to all participants!*"
                ),
                parse_mode=ParseMode.MARKDOWN
            )

        except Exception:
            pass

        await asyncio.sleep(1)

        chat_data[countdown_key] = False
        chat_data[ready_key] = set()

        await deliver_group_question(
            context,
            chat.id,
            session_id
        )

        return

    # =========================================================
    # 17. QUIZ STATISTICS
    # =========================================================

    elif data.startswith("stats:"):

        quiz_code = data.split(":", 1)[1]

        with get_db() as db:

            quiz = QuizRepository.get_by_code(
                db,
                quiz_code
            )

            if not quiz:

                await chat.send_message(
                    t("quiz_not_found")
                )

                return

            completed_attempts = [
                attempt
                for attempt in quiz.attempts
                if attempt.status == "COMPLETED"
            ]

            total_attempts = len(
                completed_attempts
            )

            if total_attempts > 0:

                scores = [
                    attempt.score
                    for attempt in completed_attempts
                ]

                avg_score = round(
                    sum(scores) / total_attempts,
                    2
                )

                high_score = max(scores)
                low_score = min(scores)

            else:

                avg_score = 0.0
                high_score = 0.0
                low_score = 0.0

            total_questions = len(
                quiz.questions
            )

            quiz_title = quiz.title

        stats_msg = (
            f"📊 *Quiz Stats: {quiz_title}*\n\n"
            f"Total Questions: {total_questions}\n"
            f"Total Attempts: {total_attempts}\n"
            f"Average Score: {avg_score}\n"
            f"Highest Score: {high_score}\n"
            f"Lowest Score: {low_score}\n"
        )

        await chat.send_message(
            text=stats_msg,
            parse_mode=ParseMode.MARKDOWN
        )

        return

    # =========================================================
    # UNKNOWN CALLBACK
    # =========================================================

    else:

        logger.warning(
            f"Unknown callback data received: {data}"
        )

        try:
            await query.answer(
                "This button is no longer available.",
                show_alert=True
            )
        except Exception:
            pass
