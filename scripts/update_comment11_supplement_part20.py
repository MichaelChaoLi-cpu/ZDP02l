#!/usr/bin/env python3
"""Apply reviewer-1/comment-11 Part 20 as one atomic OOXML text edit."""

from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZipFile
import os


DOCX = Path("Rev/revision/ZDP02l.supplementary.docx")
BEFORE = b"Rows follow the same UN M49 region and within-region place order as Figure 6."
AFTER = b"Rows follow the same UN M49 region and within-region place order as Figure 2."


def main() -> None:
    with ZipFile(DOCX, "r") as source:
        document_xml = source.read("word/document.xml")
        count = document_xml.count(BEFORE)
        if count != 1:
            raise SystemExit(f"expected one exact target, found {count}")
        revised_xml = document_xml.replace(BEFORE, AFTER, 1)

        with NamedTemporaryFile(
            prefix=f".{DOCX.name}.", suffix=".tmp", dir=DOCX.parent, delete=False
        ) as handle:
            staged_path = Path(handle.name)

        try:
            with ZipFile(staged_path, "w") as staged:
                for info in source.infolist():
                    payload = revised_xml if info.filename == "word/document.xml" else source.read(info.filename)
                    staged.writestr(info, payload)
            os.replace(staged_path, DOCX)
        finally:
            staged_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
