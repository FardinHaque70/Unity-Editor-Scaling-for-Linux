"""Editor setting state, independent of GTK and filesystem operations."""
from dataclasses import dataclass
import re


def parse_scale(text: str) -> int | None:
    if not re.fullmatch(r"[0-9]{3}", text):
        return None
    value = int(text)
    return value if 100 <= value <= 200 else None


@dataclass(frozen=True)
class SaveRequest:
    revision: int
    scale: int
    override: bool
    save_scale: bool


class EditorEditState:
    def __init__(self, scale=150, override=False):
        self.saved_scale = int(scale)
        self.saved_override = bool(override)
        self.text = str(self.saved_scale)
        self.override = bool(override)
        self.revision = 0
        self.inflight = None
        self.error = None

    @property
    def value(self):
        return parse_scale(self.text)

    @property
    def dirty(self):
        return self.value != self.saved_scale or self.override != self.saved_override

    @property
    def pending(self):
        return self.dirty or self.inflight is not None

    def edit_text(self, text):
        if text != self.text:
            self.text = text
            self.revision += 1
            self.error = None

    def set_override(self, enabled):
        if bool(enabled) != self.override:
            self.override = bool(enabled)
            self.revision += 1
            self.error = None

    def begin(self):
        if self.inflight or not self.dirty:
            return None
        value = self.value
        if value is None and (self.override or self.override == self.saved_override):
            return None
        request = SaveRequest(self.revision, self.saved_scale if value is None else value,
                              self.override, value is not None and value != self.saved_scale)
        self.inflight = request
        self.error = None
        return request

    def complete(self, request, *, error=None):
        if self.inflight != request:
            raise ValueError("Completion does not match the active save")
        self.inflight = None
        if error is not None:
            self.error = str(error)
            return
        if request.save_scale:
            self.saved_scale = request.scale
        self.saved_override = request.override
        self.error = None

    def discard(self):
        if self.inflight:
            raise ValueError("An active save must finish before discarding queued edits")
        self.text = str(self.saved_scale)
        self.override = self.saved_override
        self.error = None
        self.revision += 1

    def subtitle(self, running=None, *, attention=False):
        if running is not None and not self.saved_override:
            detail = f"Running {running:g}% · Override off next launch"
        elif running is not None:
            detail = (f"Running {running:g}% · Next {self.saved_scale}%"
                      if running != self.saved_scale else f"Running {running:g}%")
        else:
            detail = (f"{self.saved_scale}% · Unity Hub integration enabled" if self.saved_override else
                      "Override off")
        if self.error:
            return detail + " · Not saved"
        if self.inflight:
            return detail + " · Saving…"
        if self.value is None:
            return detail + " · Invalid value"
        if attention:
            return detail + " · Needs attention"
        return detail
