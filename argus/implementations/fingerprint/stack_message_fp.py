"""Stack+message fingerprint algorithm."""
from __future__ import annotations
import hashlib
import re
from argus.models.event import RawEvent
from argus.interfaces.fingerprinter import Fingerprint


class StackMessageFingerprinter:
    """Fingerprint by stack top-N frames + exception type + normalized message."""

    NUMBER_RE = re.compile(r'\d+')
    UUID_RE = re.compile(
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
        re.IGNORECASE,
    )
    IP_RE = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')

    def __init__(self, stack_top_n: int = 5):
        self.stack_top_n = stack_top_n

    def fingerprint(self, event: RawEvent) -> Fingerprint:
        exception_type = self._normalize(self._extract_exception_type(event.raw_message))
        template_msg = self._normalize(event.raw_message)
        top_frames = (
            self._extract_top_frames(event.stack_trace)
            if event.stack_trace
            else []
        )

        hash_input = f"{exception_type}|{template_msg}|{'|'.join(top_frames)}"
        fp_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16]

        return Fingerprint(
            hash=fp_hash,
            exception_type=exception_type,
            template_message=template_msg,
            top_frames=top_frames,
        )

    def is_same_group(self, fp1: Fingerprint, fp2: Fingerprint) -> bool:
        return fp1.hash == fp2.hash

    def _extract_exception_type(self, message: str) -> str:
        match = re.match(r'^(\w+(?:Error|Exception|Warning))', message)
        if match:
            return match.group(1)
        return message.split(':')[0].strip() if ':' in message else message[:50]

    def _normalize(self, text: str) -> str:
        text = self.UUID_RE.sub('<UUID>', text)
        text = self.IP_RE.sub('<IP>', text)
        text = self.NUMBER_RE.sub('<N>', text)
        return text

    def _extract_top_frames(self, stack_trace: str) -> list[str]:
        lines = stack_trace.strip().split('\n')
        frames = []
        for line in lines:
            match = re.search(r'File\s+"([^"]+)",\s*line\s+(\d+)', line)
            if match:
                frames.append(f"{match.group(1)}:{match.group(2)}")
            if len(frames) >= self.stack_top_n:
                break
        return frames
