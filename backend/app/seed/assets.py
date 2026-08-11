import asyncio
from collections.abc import Iterator

import httpx
import numpy as np
import structlog
from pydantic import BaseModel

from app.config import Settings
from app.models.enums import FrameIntegrity
from app.seed.images import RenderedImage, render_cine_frame, render_still, render_thumbnail
from app.seed.plan import SeedPlan

logger = structlog.get_logger(__name__)

#: Bounded so a full-profile run does not open thousands of sockets against the free tier.
MAX_CONCURRENT_UPLOADS = 16
_UPLOAD_TIMEOUT_SECONDS = 30.0

#: Refuse to exceed this much storage. The free tier allows 1 GB across the project.
MAX_TOTAL_BYTES = 700 * 1024 * 1024


class UploadSummary(BaseModel):
    """Outcome of an upload pass."""

    uploaded: int
    skipped: int
    total_bytes: int
    sizes: dict[str, int]


def _render_objects(plan: SeedPlan) -> Iterator[tuple[str, RenderedImage]]:
    """Yield every storage object the plan implies, rendering on demand.

    A generator rather than a list so a full-profile run never holds thousands of encoded
    frames in memory at once.

    Args:
        plan: The dataset to render.

    Yields:
        Storage path and the encoded image to upload there.
    """
    for study in plan.studies:
        for image in study.images:
            rng = np.random.default_rng(abs(hash(image.id)) % (2**32))
            still = render_still(rng)
            yield image.storage_path, still
            yield image.thumbnail_path, render_thumbnail(still)

        for clip in study.clips:
            for frame in clip.frames:
                if frame.integrity is not FrameIntegrity.OK:
                    # Deliberately absent from storage, so the viewer's gap handling is
                    # exercised against a genuinely missing object.
                    continue
                rng = np.random.default_rng(abs(hash(frame.id)) % (2**32))
                yield frame.storage_path, render_cine_frame(rng, frame.sequence, clip.frame_count)


async def _upload_one(
    client: httpx.AsyncClient,
    settings: Settings,
    semaphore: asyncio.Semaphore,
    path: str,
    image: RenderedImage,
) -> None:
    """Upload a single object, overwriting any existing one.

    Args:
        client: HTTP client.
        settings: Application settings.
        semaphore: Concurrency limiter.
        path: Destination storage path.
        image: Encoded image to upload.

    Raises:
        httpx.HTTPStatusError: If the upload is rejected.
    """
    async with semaphore:
        response = await client.post(
            f"{settings.supabase_url}/storage/v1/object/{settings.supabase_storage_bucket}/{path}",
            content=image.data,
            headers={"content-type": "image/jpeg", "x-upsert": "true"},
        )
        response.raise_for_status()


async def upload_plan(
    plan: SeedPlan,
    settings: Settings,
    *,
    existing: set[str] | None = None,
    dry_run: bool = False,
) -> UploadSummary:
    """Render and upload every asset the plan implies.

    Args:
        plan: The dataset to upload.
        settings: Application settings.
        existing: Object paths already stored, which are skipped. Supplying this is what
            makes an interrupted run resumable rather than restarting from scratch.
        dry_run: Render and measure without uploading.

    Returns:
        Counts and per-path encoded sizes.

    Raises:
        RuntimeError: If the rendered dataset would exceed the storage budget.
    """
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
    }
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_UPLOADS)
    sizes: dict[str, int] = {}
    uploaded = 0
    skipped = 0
    total_bytes = 0

    async with httpx.AsyncClient(timeout=_UPLOAD_TIMEOUT_SECONDS, headers=headers) as client:
        present = set[str]() if dry_run else (existing or set[str]())
        logger.info("seed.upload_start", planned=plan.asset_count(), already_present=len(present))

        pending: list[asyncio.Task[None]] = []
        for path, image in _render_objects(plan):
            sizes[path] = image.byte_size
            total_bytes += image.byte_size
            if total_bytes > MAX_TOTAL_BYTES:
                raise RuntimeError(
                    f"rendered dataset would exceed the storage budget "
                    f"({total_bytes / 1024 / 1024:.0f} MB > "
                    f"{MAX_TOTAL_BYTES / 1024 / 1024:.0f} MB)"
                )
            if dry_run:
                continue
            if path in present:
                skipped += 1
                continue
            pending.append(
                asyncio.create_task(_upload_one(client, settings, semaphore, path, image))
            )
            uploaded += 1
            # Drain periodically so the task list cannot grow to the size of the dataset.
            if len(pending) >= MAX_CONCURRENT_UPLOADS * 8:
                await asyncio.gather(*pending)
                pending.clear()
                logger.info("seed.upload_progress", uploaded=uploaded, skipped=skipped)

        if pending:
            await asyncio.gather(*pending)

    logger.info(
        "seed.upload_complete",
        uploaded=uploaded,
        skipped=skipped,
        megabytes=round(total_bytes / 1024 / 1024, 1),
    )
    return UploadSummary(uploaded=uploaded, skipped=skipped, total_bytes=total_bytes, sizes=sizes)
