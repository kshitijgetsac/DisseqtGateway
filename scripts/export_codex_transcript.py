#!/usr/bin/env python3
"""Export shareable conversation and tool history from a Codex rollout JSONL."""

import argparse
import collections
import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


REDACTIONS = (
    ("private key", re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----.*?"
        r"-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", re.I | re.S)),
    ("binary data URL", re.compile(
        r"data:(?:image|audio|application)/[\w.+-]+;base64,[A-Za-z0-9+/=]+", re.I)),
    ("bearer token", re.compile(
        r"(?i)(\bBearer\s+)(?:[A-Za-z0-9._~+/=-]{4,}|\$[A-Za-z_][A-Za-z_0-9]*)")),
    ("credential token", re.compile(
        r"(?i)\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{8,}|"
        r"github_pat_[A-Za-z0-9_]{8,}|glpat-[A-Za-z0-9_-]{8,}|"
        r"xox[baprs]-[A-Za-z0-9-]{8,}|AKIA[0-9A-Z]{16}|ag_[A-Za-z0-9_]{8,}|"
        r"dodo_(?:test|live)_[A-Za-z0-9_]{8,}|gateway_demo_only|"
        r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b")),
    ("secret field", re.compile(
        r"(?i)([\"']?\b(?:api[_-]?key|secret(?:[_-]?key)?|access[_-]?token|"
        r"refresh[_-]?token|auth[_-]?token|password|passwd|client[_-]?secret|"
        r"postgres[_-]?password|database[_-]?url|cookie)[\"']?\s*[:=]\s*[\"']?)"
        r"([^\s,;\"'}\]]{3,})")),
    ("URL password", re.compile(
        r"(?i)(\b(?:postgres(?:ql)?(?:\+[a-z0-9_]+)?|mysql|mongodb(?:\+srv)?|redis)://[^\s:@/]+:)"
        r"([^@\s/]+)(@)")),
)


def visible_text(items):
    parts = []
    for item in items:
        item_type = item.get("type")
        if item_type in {"input_text", "output_text", "text"}:
            parts.append(item.get("text", ""))
        elif item_type in {"input_image", "output_image", "image"}:
            parts.append("[Binary image omitted from the text transcript.]" )
    return "\n".join(parts)


def extract_entries(source):
    entries = []
    tool_names = {}
    with open(source, encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") != "response_item":
                continue
            payload = record.get("payload", {})
            kind = payload.get("type")
            timestamp = record.get("timestamp", "")
            if kind == "message":
                role = payload.get("role")
                if role == "user":
                    body = visible_text(payload.get("content", []))
                    if body:
                        entries.append((timestamp, "USER", body))
                elif role == "assistant" and payload.get("phase") in {"commentary", "final_answer"}:
                    body = visible_text(payload.get("content", []))
                    if body:
                        label = "ASSISTANT" if payload.get("phase") == "final_answer" else "ASSISTANT · PROGRESS"
                        entries.append((timestamp, label, body))
            elif kind in {"custom_tool_call", "function_call"}:
                name = payload.get("name", "tool")
                if payload.get("namespace"):
                    name = f"{payload['namespace']}.{name}"
                tool_names[payload.get("call_id")] = name
                entries.append((timestamp, f"TOOL CALL · {name}",
                                str(payload.get("input", payload.get("arguments", "")))))
            elif kind in {"custom_tool_call_output", "function_call_output"}:
                output = payload.get("output", "")
                if isinstance(output, list):
                    output = visible_text(output)
                name = tool_names.get(payload.get("call_id"), "tool")
                entries.append((timestamp, f"TOOL RESULT · {name}", str(output)))
    return entries


def redact(text, counts):
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    for label, pattern in REDACTIONS:
        if label == "bearer token":
            text, count = pattern.subn(lambda match: match.group(1) + "[REDACTED]", text)
        elif label == "secret field":
            text, count = pattern.subn(lambda match: match.group(1) + "[REDACTED]", text)
        elif label == "URL password":
            text, count = pattern.subn(
                lambda match: match.group(1) + "[REDACTED]" + match.group(3), text)
        else:
            text, count = pattern.subn(f"[REDACTED: {label}]", text)
        counts[label] += count
    return text


def render(entries, output, counts):
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    pdfmetrics.registerFont(TTFont("Arial", "/System/Library/Fonts/Supplemental/Arial.ttf"))
    pdfmetrics.registerFont(TTFont("Arial-Bold", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"))
    pdfmetrics.registerFont(TTFont("CourierNew", "/System/Library/Fonts/Supplemental/Courier New.ttf"))

    width, height = A4
    margin, top, bottom = 43, height - 45, 48
    page, y = 1, top
    pdf = canvas.Canvas(output, pagesize=A4, pageCompression=1)
    pdf.setTitle("Redacted Codex Session Transcript")
    pdf.setAuthor("Codex transcript export")

    def frame():
        nonlocal y
        pdf.setFillColorRGB(.12, .19, .28)
        pdf.setFont("Arial-Bold", 9)
        pdf.drawString(margin, height - 28, "Codex session transcript · redacted")
        pdf.setStrokeColorRGB(.78, .82, .86)
        pdf.line(margin, height - 34, width - margin, height - 34)
        pdf.setFont("Arial", 7)
        pdf.setFillColorRGB(.38, .43, .48)
        pdf.drawString(margin, 27, "Times: Asia/Kolkata (IST) · Source: local Codex session log")
        pdf.drawRightString(width - margin, 27, str(page))
        y = top

    def new_page():
        nonlocal page
        pdf.showPage()
        page += 1
        frame()

    def draw_line(text, font="CourierNew", size=7.4, color=(.16, .18, .2), gap=9.3):
        nonlocal y
        if y < bottom:
            new_page()
        pdf.setFont(font, size)
        pdf.setFillColorRGB(*color)
        pdf.drawString(margin, y, text)
        y -= gap

    def wrap(text, font="CourierNew", size=7.4):
        available = width - 2 * margin
        if not text:
            return [""]
        lines, current = [], ""
        for token in re.findall(r"\S+|\s+", text):
            candidate = current + token
            if pdfmetrics.stringWidth(candidate, font, size) <= available:
                current = candidate
                continue
            if current:
                lines.append(current)
                current = ""
            if pdfmetrics.stringWidth(token, font, size) <= available:
                current = token
                continue
            fragment = ""
            for char in token:
                if fragment and pdfmetrics.stringWidth(fragment + char, font, size) > available:
                    lines.append(fragment)
                    fragment = char
                else:
                    fragment += char
            current = fragment
        if current:
            lines.append(current)
        return lines or [""]

    frame()
    draw_line("Session transcript", font="Arial-Bold", size=17, color=(.08, .17, .28), gap=24)
    draw_line("Conversation and textual tool history from the local Codex rollout log.", font="Arial", size=9, gap=15)
    draw_line("Internal instructions, private reasoning, runtime metadata, and binary images are excluded.", font="Arial", size=9, gap=15)
    draw_line("Credential-like values are replaced with [REDACTED].", font="Arial", size=9, gap=18)
    labels = collections.Counter(label.split(" · ")[0] for _, label, _ in entries)
    for label in ("USER", "ASSISTANT", "TOOL CALL", "TOOL RESULT"):
        draw_line(f"{label}: {labels[label]}", font="Arial", size=9, gap=14)
    summary = ", ".join(f"{label} {count}" for label, count in counts.items() if count)
    draw_line("Redactions: " + (summary or "no credential-like values found"), font="Arial", size=9, gap=18)
    draw_line("Original attachments remain available in the Codex task.", font="Arial", size=8.5, gap=18)
    new_page()

    for index, (timestamp, label, body) in enumerate(entries, 1):
        if y < bottom + 35:
            new_page()
        try:
            local = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(
                ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S IST")
        except ValueError:
            local = timestamp
        color = (.12, .34, .54) if label.startswith("USER") else (
            (.18, .42, .25) if label.startswith("ASSISTANT") else (.41, .32, .42))
        for piece in wrap(f"{index:04d}  {local}  {label}", "Arial-Bold", 8.3):
            draw_line(piece, font="Arial-Bold", size=8.3, color=color, gap=12)
        for source_line in body.splitlines() or [""]:
            for piece in wrap(source_line.replace("\t", "    ")):
                draw_line(piece)
        y -= 6
    pdf.save()
    return page


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("output")
    args = parser.parse_args()
    counts = collections.Counter()
    entries = [(timestamp, label, redact(body, counts))
               for timestamp, label, body in extract_entries(args.source)]
    pages = render(entries, args.output, counts)
    print(json.dumps({"output": os.path.abspath(args.output), "pages": pages,
                      "entries": len(entries), "redactions": dict(counts)}))


if __name__ == "__main__":
    main()
