import io
import math

import numpy as np
import numpy.typing as npt
from PIL import Image
from pydantic import BaseModel

#: Frame dimensions. Small on purpose — these are mock images standing in for a modality,
#: and the free storage tier is 1 GB across the whole seeded dataset.
STILL_SIZE = (512, 384)
CINE_SIZE = (320, 240)
THUMBNAIL_SIZE = (96, 72)

STILL_QUALITY = 72
CINE_QUALITY = 60
THUMBNAIL_QUALITY = 55

_SECTOR_HALF_ANGLE = math.radians(40)


class RenderedImage(BaseModel):
    """An encoded image and the metadata the database records for it."""

    data: bytes
    width: int
    height: int

    @property
    def byte_size(self) -> int:
        """Return the encoded size in bytes.

        Returns:
            Length of the encoded image.
        """
        return len(self.data)


#: Speckle is generated at a fraction of full resolution and scaled up. Per-pixel noise
#: reads as television static rather than tissue, and being incompressible it roughly
#: doubles the encoded size of every frame.
_SPECKLE_SCALE = 4


def _speckle(size: tuple[int, int], rng: np.random.Generator) -> npt.NDArray[np.float64]:
    """Generate spatially correlated speckle for one frame.

    Args:
        size: Output (width, height).
        rng: Seeded generator.

    Returns:
        A float array of shape (height, width) with mean near 1.
    """
    width, height = size
    coarse_shape = (
        max(height // _SPECKLE_SCALE, 1),
        max(width // _SPECKLE_SCALE, 1),
    )
    # Gamma-distributed multiplicative noise is the standard speckle model.
    coarse = rng.gamma(shape=2.2, scale=0.46, size=coarse_shape)
    grain = np.array(
        Image.fromarray((np.clip(coarse, 0, 2.2) * 116).astype(np.uint8)).resize(
            (width, height), Image.Resampling.BILINEAR
        ),
        dtype=np.float64,
    )
    # A little fine noise on top keeps it from looking airbrushed.
    return grain / 116.0 * rng.uniform(0.88, 1.12, size=(height, width))


def _sector_field(
    size: tuple[int, int],
    rng: np.random.Generator,
    lesion_centre: tuple[float, float] | None,
    lesion_radius: float,
) -> npt.NDArray[np.uint8]:
    """Render one ultrasound-like sector scan as a grayscale array.

    Builds a fan from an apex at the top, fills it with gamma-distributed speckle that
    attenuates with depth, and optionally darkens a circular anechoic region.

    Args:
        size: Output (width, height).
        rng: Seeded generator, so a given frame always renders identically.
        lesion_centre: Pixel centre of the anechoic region, or None for none.
        lesion_radius: Radius of that region in pixels.

    Returns:
        A uint8 array of shape (height, width).
    """
    width, height = size
    ys, xs = np.mgrid[0:height, 0:width]

    apex_x = width / 2.0
    dx = xs - apex_x
    dy = ys.astype(np.float64) + 1.0
    radius = np.hypot(dx, dy)
    angle = np.arctan2(dx, dy)

    max_radius = height * 0.98
    inside = (
        (np.abs(angle) <= _SECTOR_HALF_ANGLE) & (radius <= max_radius) & (radius >= height * 0.05)
    )

    # Echo strength falls off with depth, giving the bright near-field and dim far-field.
    depth = np.clip(radius / max_radius, 0.0, 1.0)
    attenuation = np.exp(-2.1 * depth) * 0.82 + 0.06

    field: npt.NDArray[np.float64] = attenuation * _speckle(size, rng)

    if lesion_centre is not None and lesion_radius > 0:
        lesion = np.hypot(xs - lesion_centre[0], ys - lesion_centre[1])
        # Anechoic structures return almost nothing, with a slightly brighter rim.
        field = np.where(lesion < lesion_radius, field * 0.07, field)
        rim = (lesion >= lesion_radius) & (lesion < lesion_radius + 2.0)
        field = np.where(rim, np.minimum(field * 2.4, 1.0), field)

    field = np.where(inside, field, 0.0)
    return np.clip(field * 255.0, 0, 255).astype(np.uint8)


def _encode(array: npt.NDArray[np.uint8], quality: int) -> RenderedImage:
    """Encode a grayscale array as JPEG.

    Args:
        array: uint8 array of shape (height, width).
        quality: JPEG quality setting.

    Returns:
        The encoded image with its dimensions.
    """
    image = Image.fromarray(array, mode="L")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return RenderedImage(data=buffer.getvalue(), width=image.width, height=image.height)


def render_still(rng: np.random.Generator) -> RenderedImage:
    """Render a single static ultrasound image.

    Args:
        rng: Seeded generator.

    Returns:
        The encoded still.
    """
    width, height = STILL_SIZE
    centre = (width / 2.0 + rng.uniform(-40, 40), height * rng.uniform(0.45, 0.65))
    radius = rng.uniform(18, 34)
    return _encode(_sector_field(STILL_SIZE, rng, centre, radius), STILL_QUALITY)


def render_cine_frame(rng: np.random.Generator, index: int, frame_count: int) -> RenderedImage:
    """Render one frame of a cine loop.

    The anechoic region traces a smooth loop across the sequence and pulses in size, so
    playback is visibly animated and a dropped or out-of-order frame is obvious on screen
    rather than only in the data.

    Args:
        rng: Seeded generator.
        index: Zero-based frame position.
        frame_count: Total frames in the clip.

    Returns:
        The encoded frame.
    """
    width, height = CINE_SIZE
    phase = 2.0 * math.pi * index / max(frame_count, 1)
    centre = (
        width / 2.0 + math.sin(phase) * width * 0.16,
        height * 0.52 + math.cos(phase) * height * 0.12,
    )
    radius = 14.0 + 5.0 * math.sin(phase * 2.0)
    return _encode(_sector_field(CINE_SIZE, rng, centre, radius), CINE_QUALITY)


def render_thumbnail(source: RenderedImage) -> RenderedImage:
    """Downscale an encoded image to a thumbnail.

    Thumbnail-first loading (Stretch #16) needs a separate small object; deriving it from
    the full frame keeps the two visually consistent.

    Args:
        source: The full-size encoded image.

    Returns:
        The encoded thumbnail.
    """
    image = Image.open(io.BytesIO(source.data))
    image.thumbnail(THUMBNAIL_SIZE)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=THUMBNAIL_QUALITY, optimize=True)
    return RenderedImage(data=buffer.getvalue(), width=image.width, height=image.height)
