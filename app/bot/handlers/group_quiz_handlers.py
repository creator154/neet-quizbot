"""Group Quiz execution, poll dispatching, and Top-3 certificate results."""

import asyncio
import io
from PIL import Image, ImageDraw, ImageFont

from telegram.constants import PollType
from telegram.ext import ContextTypes

from app.database.connection import get_db
from app.services.group_quiz_service import GroupQuizService
from app.utils.logger import logger


# Prevent the same completed session from sending the result more than once
_RESULT_SENT_SESSIONS = set()
_RESULT_LOCK = asyncio.Lock()


def _get_font(size: int, bold: bool = False):
    """Load a commonly available Unicode font."""
    path = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    )
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _fit_text(draw, text, max_width, font_size, bold=False):
    """Reduce font size until text fits."""
    size = font_size

    while size >= 20:
        font = _get_font(size, bold)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
        size -= 2

    return _get_font(20, bold)


def _create_certificate(
    name: str,
    rank: int,
    score,
    quiz_title: str,
    group_name: str,
    correct: int,
    wrong: int,
    skipped: int,
) -> io.BytesIO:
    """Create a certificate-style PNG in memory."""

    width = 1600
    height = 1000

    image = Image.new("RGB", (width, height), "#f8f5ed")
    draw = ImageDraw.Draw(image)

    # Outer borders
    draw.rectangle(
        (35, 35, width - 35, height - 35),
        outline="#1f2937",
        width=8,
    )

    draw.rectangle(
        (55, 55, width - 55, height - 55),
        outline="#c49a3a",
        width=4,
    )

    # Header
    title_font = _get_font(72, True)
    subtitle_font = _get_font(32, False)
    name_font = _fit_text(
        draw,
        name,
        1300,
        64,
        True,
    )

    rank_font = _get_font(52, True)
    score_font = _get_font(48, True)
    small_font = _get_font(28, False)
    credit_font = _get_font(30, True)

    # Main heading
    heading = "QUIZ ACHIEVEMENT"
    bbox = draw.textbbox((0, 0), heading, font=title_font)
    draw.text(
        ((width - (bbox[2] - bbox[0])) / 2, 105),
        heading,
        fill="#172033",
        font=title_font,
    )

    subtitle = "CERTIFICATE OF PERFORMANCE"
    bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    draw.text(
        ((width - (bbox[2] - bbox[0])) / 2, 195),
        subtitle,
        fill="#8a6a22",
        font=subtitle_font,
    )

    # Decorative line
    draw.line(
        (250, 255, width - 250, 255),
        fill="#c49a3a",
        width=4,
    )

    # Presented to
    presented = "Presented to"
    bbox = draw.textbbox((0, 0), presented, font=subtitle_font)
    draw.text(
        ((width - (bbox[2] - bbox[0])) / 2, 315),
        presented,
        fill="#4b5563",
        font=subtitle_font,
    )

    # Participant name
    bbox = draw.textbbox((0, 0), name, font=name_font)
    draw.text(
        ((width - (bbox[2] - bbox[0])) / 2, 365),
        name,
        fill="#111827",
        font=name_font,
    )

    # Rank badge
    medal = {
        1: "🥇",
        2: "🥈",
        3: "🥉",
    }.get(rank, "")

    rank_text = f"{medal}  RANK #{rank}"
    bbox = draw.textbbox((0, 0), rank_text, font=rank_font)

    draw.text(
        ((width - (bbox[2] - bbox[0])) / 2, 470),
        rank_text,
        fill="#9a741f",
        font=rank_font,
    )

    # Quiz title
    quiz_font = _fit_text(
        draw,
        quiz_title,
        1200,
        34,
        True,
    )

    bbox = draw.textbbox((0, 0), quiz_title, font=quiz_font)

    draw.text(
        ((width - (bbox[2] - bbox[0])) / 2, 555),
        quiz_title,
        fill="#263244",
        font=quiz_font,
    )

    # Score
    score_text = f"Score: {score}"
    bbox = draw.textbbox((0, 0), score_text, font=score_font)

    draw.text(
        ((width - (bbox[2] - bbox[0])) / 2, 625),
        score_text,
        fill="#111827",
        font=score_font,
    )

    # Stats
    stats = (
        f"Correct: {correct}    "
        f"Wrong: {wrong}    "
        f"Skipped: {skipped}"
    )

    bbox = draw.textbbox((0, 0), stats, font=small_font)

    draw.text(
        ((width - (bbox[2] - bbox[0])) / 2, 700),
        stats,
        fill="#4b5563",
        font=small_font,
    )

    # Group
    group_text = f"Group: {group_name}"

    group_font = _fit_text(
        draw,
        group_text,
        1250,
        28,
        False,
    )

    bbox = draw.textbbox((0, 0), group_text, font=group_font)

    draw.text(
        ((width - (bbox[2] - bbox[0])) / 2, 765),
        group_text,
        fill="#374151",
        font=group_font,
    )

    # Credit
    credit = "Credit by Sumit"

    bbox = draw.textbbox((0, 0), credit, font=credit_font)

    draw.text(
        ((width - (bbox[2] - bbox[0])) / 2, 865),
        credit,
        fill="#8a6a22",
        font=credit_font,
    )

    output = io.BytesIO()
    output.name = f"certificate_rank_{rank}.png"

    image.save(
        output,
        format="PNG",
        optimize=True,
    )

    output.seek(0)

    return output


async def on_group_question_timeout(
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Callback fired when the timer for a group question expires."""

    job_data = context.job.data if context.job else None

    if not job_data:
        return

    chat_id = job_data["chat_id"]
    session_id = job_data["session_id"]

    with get_db() as db:
        is_finished, session = (
            GroupQuizService.advance_question_or_finish(
                db,
                session_id,
            )
        )

    if is_finished:
        await send_group_leaderboard(
            context,
            chat_id,
            session_id,
        )

    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⌛ Time's up! Next question coming up...",
        )

        await asyncio.sleep(2)

        await deliver_group_question(
            context,
            chat_id,
            session_id,
        )


async def deliver_group_question(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    session_id: int,
) -> None:
    """Send the current question to the group."""

    with get_db() as db:
        payload = GroupQuizService.get_current_question_payload(
            db,
            session_id,
        )

    if not payload:
        await send_group_leaderboard(
            context,
            chat_id,
            session_id,
        )
        return

    # ------------------------------------------------------------
    # 1. PRE-QUESTION MEDIA
    # ------------------------------------------------------------

    media_file = payload.get("media_file_id")
    media_type = payload.get("media_type")

    if media_file and media_type:
        try:
            if media_type == "photo":
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=media_file,
                )

            elif media_type == "video":
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=media_file,
                )

            elif media_type == "animation":
                await context.bot.send_animation(
                    chat_id=chat_id,
                    animation=media_file,
                )

            elif media_type == "document":
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=media_file,
                )

            elif media_type == "text":
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"ℹ️ Note:\n{media_file}",
                )

        except Exception as e:
            logger.error(
                f"Error sending group pre-question media: {e}",
                exc_info=True,
            )

    # ------------------------------------------------------------
    # 2. SEND POLL
    # ------------------------------------------------------------

    timer_seconds = payload.get(
        "timer_seconds",
        30,
    )

    open_period = (
        timer_seconds
        if 5 <= timer_seconds <= 600
        else 30
    )

    q_title = (
        f"[{payload['display_position']}/"
        f"{payload['total_questions']}] "
        f"{payload['question_text']}"
    )

    try:
        poll_msg = await context.bot.send_poll(
            chat_id=chat_id,
            question=q_title,
            options=payload["options"],
            type=PollType.QUIZ,
            is_anonymous=False,
            correct_option_id=payload["correct_option_id"],
            explanation=payload["explanation"],
            open_period=open_period,
        )

        with get_db() as db:
            GroupQuizService.record_poll_sent(
                db,
                session_id,
                poll_msg.poll.id,
            )

        # --------------------------------------------------------
        # 3. SCHEDULE TIMEOUT
        # --------------------------------------------------------

        if context.job_queue:
            context.job_queue.run_once(
                callback=on_group_question_timeout,
                when=open_period,
                chat_id=chat_id,
                name=(
                    f"grp_timer_"
                    f"{session_id}_"
                    f"{payload['question_id']}"
                ),
                data={
                    "chat_id": chat_id,
                    "session_id": session_id,
                },
            )

    except Exception as e:
        logger.error(
            f"Error sending group quiz poll: {e}",
            exc_info=True,
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"⚠️ Failed to send question "
                f"{payload['display_position']}. "
                f"Moving forward..."
            ),
        )

        with get_db() as db:
            is_fin, _ = (
                GroupQuizService.advance_question_or_finish(
                    db,
                    session_id,
                )
            )

        if is_fin:
            await send_group_leaderboard(
                context,
                chat_id,
                session_id,
            )
        else:
            await deliver_group_question(
                context,
                chat_id,
                session_id,
            )


async def send_group_leaderboard(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    session_id: int,
) -> None:
    """
    Send only Top 3 results as certificate-style images.

    No full 20-user leaderboard is sent.
    """

    # ============================================================
    # DUPLICATE RESULT PROTECTION
    # ============================================================

    async with _RESULT_LOCK:
        if session_id in _RESULT_SENT_SESSIONS:
            logger.info(
                f"Result already sent for group session "
                f"{session_id}; skipping duplicate."
            )
            return

        # Reserve the session before sending anything.
        _RESULT_SENT_SESSIONS.add(session_id)

    try:
        # ========================================================
        # GET LEADERBOARD
        # ========================================================

        with get_db() as db:
            data = GroupQuizService.generate_leaderboard_data(
                db,
                session_id,
            )

        title = data.get(
            "quiz_title",
            "Quiz",
        )

        rankings = data.get(
            "rankings",
            [],
        )

        # Only Top 3
        top_three = rankings[:3]

        if not top_three:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "🏁 QUIZ COMPLETE!\n\n"
                    "⚠️ No participants attempted the quiz."
                ),
            )
            return

        # ========================================================
        # GET GROUP NAME
        # ========================================================

        try:
            chat = await context.bot.get_chat(chat_id)

            group_name = (
                getattr(chat, "title", None)
                or "Quiz Group"
            )

        except Exception as e:
            logger.warning(
                f"Could not fetch group name: {e}"
            )
            group_name = "Quiz Group"

        # ========================================================
        # SEND TOP 3 CERTIFICATES
        # ========================================================

        for rank, participant in enumerate(
            top_three,
            start=1,
        ):
            name = participant.get(
                "name",
                "Participant",
            )

            score = participant.get(
                "score",
                0,
            )

            correct = participant.get(
                "correct",
                0,
            )

            wrong = participant.get(
                "wrong",
                0,
            )

            skipped = participant.get(
                "skipped",
                0,
            )

            certificate = _create_certificate(
                name=name,
                rank=rank,
                score=score,
                quiz_title=title,
                group_name=group_name,
                correct=correct,
                wrong=wrong,
                skipped=skipped,
            )

            await context.bot.send_photo(
                chat_id=chat_id,
                photo=certificate,
                caption=(
                    f"🏆 Rank #{rank}\n"
                    f"👤 {name}\n"
                    f"📊 Score: {score}"
                ),
            )

            # Small delay so Telegram doesn't get flooded
            if rank < len(top_three):
                await asyncio.sleep(0.5)

        logger.info(
            f"Top 3 certificate results sent for "
            f"group session {session_id}."
        )

    except Exception:
        # If sending failed, allow retry rather than permanently
        # marking this session as completed.
        async with _RESULT_LOCK:
            _RESULT_SENT_SESSIONS.discard(session_id)

        logger.error(
            f"Error sending Top 3 results for session "
            f"{session_id}",
            exc_info=True,
        )

        raise
