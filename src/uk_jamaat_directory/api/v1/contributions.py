from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from uk_jamaat_directory.api.rate_limit import limit_community_submissions
from uk_jamaat_directory.db.session import get_db_session
from uk_jamaat_directory.schemas.contributions import (
    CommunityMosqueSubmission,
    CommunityMosqueSubmissionResponse,
)
from uk_jamaat_directory.services import community_submissions

router = APIRouter(prefix="/contributions", tags=["contributions"])


@router.post(
    "/mosques",
    response_model=CommunityMosqueSubmissionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(limit_community_submissions)],
)
async def submit_mosque(
    payload: CommunityMosqueSubmission,
    session: AsyncSession = Depends(get_db_session),
) -> CommunityMosqueSubmissionResponse:
    submission_id, review_status = await community_submissions.submit_community_mosque(
        session,
        payload,
    )
    await session.commit()
    return CommunityMosqueSubmissionResponse(
        submission_id=submission_id,
        status=review_status,
        message="Submission received and queued for moderation.",
    )
