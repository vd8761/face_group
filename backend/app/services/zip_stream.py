"""Build valid ZIP archives on local disk and stream them in bounded chunks."""
import os
import tempfile
import zipfile
from pathlib import Path
from typing import AsyncIterator, List

from fastapi.concurrency import run_in_threadpool

from ..services.storage import stream_object


async def stream_zip(
    keys_and_names: List[tuple[str, str]],
    chunk_size: int = 1024 * 64,
) -> AsyncIterator[bytes]:
    """Yield a ZIP while keeping image data out of application memory."""
    fd, archive_path = tempfile.mkstemp(prefix="photogroup-", suffix=".zip")
    os.close(fd)

    try:
        used_names: set[str] = set()
        with zipfile.ZipFile(
            archive_path,
            mode="w",
            compression=zipfile.ZIP_STORED,
            allowZip64=True,
        ) as archive:
            for index, (r2_key, filename) in enumerate(keys_and_names, start=1):
                safe_name = Path(filename).name or f"photo-{index}.jpg"
                if safe_name in used_names:
                    stem = Path(safe_name).stem
                    suffix = Path(safe_name).suffix
                    safe_name = f"{stem}-{index}{suffix}"
                used_names.add(safe_name)

                body = await run_in_threadpool(stream_object, r2_key)
                try:
                    with archive.open(safe_name, mode="w") as destination:
                        while True:
                            chunk = await run_in_threadpool(body.read, chunk_size)
                            if not chunk:
                                break
                            await run_in_threadpool(destination.write, chunk)
                finally:
                    await run_in_threadpool(body.close)

        with open(archive_path, "rb") as archive_file:
            while True:
                chunk = await run_in_threadpool(archive_file.read, chunk_size)
                if not chunk:
                    break
                yield chunk
    finally:
        try:
            os.remove(archive_path)
        except FileNotFoundError:
            pass
