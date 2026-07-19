from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from database import get_db
import models, schemas
from auth import get_current_user

router = APIRouter(prefix="/insights", tags=["insights"])

TREND_DAYS = 14
TOP_TOPICS_LIMIT = 10
FULL_CONVERSATIONS_LIMIT = 50


@router.get("", response_model=schemas.InsightsResponse)
def get_insights(
    room_id: Optional[str] = Query(None, description="Restrict to a single room"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Aggregate Q&A insights across ALL the sender's rooms (company dashboard).

    Full question/answer text appears only for members who consented with
    sharing_mode "full" at the time they asked.
    """
    room_query = db.query(models.Room.id).filter(models.Room.sender_id == current_user.id)
    if room_id:
        room_query = room_query.filter(models.Room.id == room_id)
        if not room_query.first():
            raise HTTPException(status_code=404, detail="Room not found")
    room_ids = [r[0] for r in room_query.all()]

    empty = {
        "total_questions": 0,
        "by_category": [],
        "trend": _empty_trend(),
        "top_topics": [],
        "full_conversations": [],
    }
    if not room_ids:
        return empty

    base = db.query(models.QAInsight).filter(models.QAInsight.room_id.in_(room_ids))

    total_questions = base.count()

    by_category = [
        {"category": category, "count": count}
        for category, count in (
            db.query(models.QAInsight.category, func.count(models.QAInsight.id))
            .filter(models.QAInsight.room_id.in_(room_ids))
            .group_by(models.QAInsight.category)
            .order_by(func.count(models.QAInsight.id).desc())
            .all()
        )
    ]

    # Daily counts for the last TREND_DAYS days, zero-filled
    since = datetime.utcnow().date() - timedelta(days=TREND_DAYS - 1)
    day_expr = func.date(models.QAInsight.created_at)
    daily = dict(
        db.query(day_expr, func.count(models.QAInsight.id))
        .filter(
            models.QAInsight.room_id.in_(room_ids),
            models.QAInsight.created_at >= datetime.combine(since, datetime.min.time()),
        )
        .group_by(day_expr)
        .all()
    )
    trend = [
        {"date": d, "count": daily.get(d, 0)}
        for d in ((since + timedelta(days=i)).isoformat() for i in range(TREND_DAYS))
    ]

    top_topics = [
        {"label": label, "count": count}
        for label, count in (
            db.query(models.QAInsight.topic_label, func.count(models.QAInsight.id))
            .filter(models.QAInsight.room_id.in_(room_ids))
            .group_by(models.QAInsight.topic_label)
            .order_by(func.count(models.QAInsight.id).desc())
            .limit(TOP_TOPICS_LIMIT)
            .all()
        )
    ]

    full_rows = (
        db.query(models.QAInsight, models.Room.name)
        .join(models.Room, models.Room.id == models.QAInsight.room_id)
        .filter(
            models.QAInsight.room_id.in_(room_ids),
            models.QAInsight.sharing_mode == "full",
            models.QAInsight.question_text.isnot(None),
        )
        .order_by(models.QAInsight.created_at.desc())
        .limit(FULL_CONVERSATIONS_LIMIT)
        .all()
    )
    full_conversations = [
        {
            "room_name": room_name,
            "asked_at": insight.created_at,
            "question": insight.question_text,
            "answer": insight.answer_text or "",
        }
        for insight, room_name in full_rows
    ]

    return {
        "total_questions": total_questions,
        "by_category": by_category,
        "trend": trend,
        "top_topics": top_topics,
        "full_conversations": full_conversations,
    }


def _empty_trend():
    since = datetime.utcnow().date() - timedelta(days=TREND_DAYS - 1)
    return [
        {"date": (since + timedelta(days=i)).isoformat(), "count": 0}
        for i in range(TREND_DAYS)
    ]
