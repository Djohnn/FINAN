from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpRequest
from django.views.decorators.http import require_GET


@require_GET
def favicon_view(request: HttpRequest) -> FileResponse:
    favicon_path = Path(settings.BASE_DIR) / "static" / "core_sistema" / "favicon.svg"
    if not favicon_path.is_file():
        raise Http404("Favicon não encontrado.")
    return FileResponse(favicon_path.open("rb"), content_type="image/svg+xml")
