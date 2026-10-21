import re

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, HttpResponseNotModified
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_safe

from .. import catalogue
from ..eo3_audio import NarrationError, narration_spec
from ..models import EO3Narration


@login_required
@require_safe
def eo3_audio(request, group, fingerprint):
    if not settings.EO3_AUDIO_ENABLED:
        raise Http404
    model = catalogue.tache_three_models().get(f"eo/tache-3/{group}")
    if model is None:
        raise Http404
    try:
        spec = narration_spec(model)
    except NarrationError:
        raise Http404 from None
    if fingerprint != spec.fingerprint:
        raise Http404
    recording = get_object_or_404(EO3Narration, fingerprint=fingerprint, group=model.group)
    audio = bytes(recording.audio)
    size = len(audio)
    etag = f'"{fingerprint}"'
    start, end, status = 0, size - 1, 200
    requested_range = request.headers.get("Range")
    if request.method == "HEAD":
        requested_range = None
    if request.headers.get("If-Range", etag) != etag:
        requested_range = None
    if requested_range:
        match = re.fullmatch(r"bytes=([0-9]{0,20})-([0-9]{0,20})", requested_range)
        if match and any(match.groups()):
            first, last = match.groups()
            if first:
                start = int(first)
                end = min(int(last), size - 1) if last else size - 1
            elif int(last):
                start = max(0, size - int(last))
            else:
                start = size
        else:
            start = size
        if not 0 <= start <= end < size:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            response["Cache-Control"] = "private, no-store"
            return response
        status = 206
    if status == 200 and request.headers.get("If-None-Match") == etag:
        response = HttpResponseNotModified()
    else:
        response = HttpResponse(
            b"" if request.method == "HEAD" else audio[start:end + 1],
            content_type="audio/mpeg", status=status,
        )
        response["Content-Length"] = str(end - start + 1)
        if status == 206:
            response["Content-Range"] = f"bytes {start}-{end}/{size}"
    response["ETag"] = etag
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "private, no-cache"
    return response
