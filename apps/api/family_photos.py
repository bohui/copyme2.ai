"""Private portraits attached to canonical people in a Family document."""
from copy import deepcopy
from io import BytesIO

import httpx
from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PHOTO_BYTES = 10 * 1024 * 1024
PHOTO_TYPES = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


def portrait_bytes(content: bytes, content_type: str) -> bytes:
    if content_type not in PHOTO_TYPES:
        raise HTTPException(415, "Use a JPEG, PNG or WebP photo")
    if not content or len(content) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "Photo must be between 1 byte and 10 MiB")
    try:
        with Image.open(BytesIO(content)) as source:
            if source.format != PHOTO_TYPES[content_type]:
                raise HTTPException(415, "Photo contents do not match its image type")
            if source.width * source.height > 36_000_000:
                raise HTTPException(413, "Photo dimensions are too large")
            image = ImageOps.exif_transpose(source).convert("RGBA")
            image.thumbnail((512, 512), Image.Resampling.LANCZOS)
            # Keep transparent portraits legible and omit camera/location metadata.
            background = Image.new("RGB", image.size, "#fffdf8")
            background.paste(image, mask=image.getchannel("A"))
            output = BytesIO()
            background.save(output, format="JPEG", quality=88, optimize=True)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(422, "The photo could not be read") from None


def family_person(document, person_id):
    person = next((person for person in (document or {}).get("people", [])
                   if person.get("id") == person_id), None)
    if person is None:
        raise HTTPException(404, "Family person not found")
    return person


def with_photo_urls(storage, document):
    if not document:
        return document
    result = deepcopy(document)
    for person in result.get("people", []):
        person.pop("photo_url", None)
        if person.get("photo_path"):
            try:
                person["photo_url"] = storage.signed_attachment_url(person["photo_path"])
            except (ValueError, httpx.HTTPError):
                # A missing portrait must not make the saved tree unreadable.
                pass
    return result


def save_person_photo(storage, project_id, person_id, photo_path):
    for attempt in range(3):
        document = deepcopy(storage.family_context(project_id))
        person = family_person(document, person_id)
        previous_path = person.pop("photo_path", None)
        person.pop("photo_url", None)
        if photo_path:
            person["photo_path"] = photo_path
        try:
            result = storage.upsert_family_context(project_id, document,
                                                    expected_revision=document.get("revision", 0))
        except httpx.HTTPStatusError as error:
            if "revision conflict" in error.response.text.lower():
                if attempt < 2:
                    continue
                raise HTTPException(409, "The family tree changed. Please try again.") from None
            raise
        saved = deepcopy(family_person(result["document"], person_id))
        if photo_path:
            try:
                saved["photo_url"] = storage.signed_attachment_url(photo_path)
            except (ValueError, httpx.HTTPError):
                # The save already succeeded; a temporary display failure is
                # recovered by the next family-context read.
                pass
        if previous_path and previous_path != photo_path:
            try:
                storage.delete_attachment(previous_path)
            except (ValueError, httpx.HTTPError):
                pass
        return {"person": saved, "revision": result["revision"]}
