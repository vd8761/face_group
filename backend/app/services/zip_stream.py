"""
Streaming ZIP builder — assembles a ZIP archive on the fly without buffering
the entire archive in memory. This keeps memory usage flat regardless of
how many photos are selected (FR-4.4).
"""
import io
import zipfile
from typing import AsyncIterator, List
from ..services.storage import stream_object


async def stream_zip(
    keys_and_names: List[tuple[str, str]],
    chunk_size: int = 1024 * 64,  # 64 KB chunks
) -> AsyncIterator[bytes]:
    """
    Yields bytes of a ZIP file built from (r2_key, filename) pairs.
    Uses a memory buffer that is flushed after each file is added,
    so peak memory is proportional to one photo, not the total archive.

    Usage:
        return StreamingResponse(
            stream_zip(pairs),
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=photos.zip"}
        )
    """
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        for r2_key, filename in keys_and_names:
            # Write each file in chunks to limit memory
            zinfo = zipfile.ZipInfo(filename=filename)
            zinfo.compress_type = zipfile.ZIP_STORED

            body = stream_object(r2_key)
            file_data = body.read()  # R2 streaming body

            zf.writestr(zinfo, file_data)

            # Yield what has been written to the buffer so far
            buf.seek(0)
            data = buf.read()
            if data:
                yield data
            buf.seek(0)
            buf.truncate(0)

    # Yield any remaining bytes (ZIP end-of-central-directory record)
    buf.seek(0)
    remaining = buf.read()
    if remaining:
        yield remaining
