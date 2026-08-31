#!/usr/bin/env python3
"""Apply the established bounded clean-only finalizer for ZDP02l."""

from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZipFile
import os

from lxml import etree


DOCX = Path("Rev/revision/ZDP02l.rev.clean.docx")
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
NS = {"w": W, "m": M}
SUPERSEDED_TITLE = (
    "Table 3. Adjusted rural-residence associations with economic-security outcomes"
)
REPLACEMENT_TITLE = (
    "Table 3. Adjusted rural-residence associations with first-stage pathway outcomes"
)


def normalized_text(node: etree._Element) -> str:
    return " ".join("".join(node.xpath(".//w:t/text()", namespaces=NS)).split())


def main() -> None:
    with ZipFile(DOCX, "r") as source:
        root = etree.fromstring(source.read("word/document.xml"))
        tables = root.xpath(".//w:tbl", namespaces=NS)
        superseded = [table for table in tables if normalized_text(table).startswith(SUPERSEDED_TITLE)]
        replacement = [table for table in tables if normalized_text(table).startswith(REPLACEMENT_TITLE)]
        if len(superseded) != 1 or len(replacement) != 1:
            raise SystemExit(
                "table guard failed: "
                f"superseded={len(superseded)}, replacement={len(replacement)}"
            )
        if len(superseded[0].xpath("./w:tr", namespaces=NS)) != 9:
            raise SystemExit("superseded Table 3 row-count guard failed")
        superseded[0].getparent().remove(superseded[0])

        empty_math = [
            node
            for node in root.xpath(".//m:oMath", namespaces=NS)
            if not "".join(node.itertext()).strip()
        ]
        # Word may retain the established empty equation shell and, after a
        # tracked paragraph replacement that reuses inline OMML, one additional
        # empty shell. Both are display-neutral and clean-copy-only artifacts.
        if len(empty_math) not in {1, 2}:
            raise SystemExit(f"empty OMML guard failed: found {len(empty_math)}")
        for node in empty_math:
            node.getparent().remove(node)

        if len(root.xpath(".//w:tbl", namespaces=NS)) != 9:
            raise SystemExit("final table-count guard failed")
        if len(root.xpath(".//m:oMath", namespaces=NS)) != 11:
            raise SystemExit("final OMML-count guard failed")
        if root.xpath(".//w:ins | .//w:del | .//w:moveTo | .//w:moveFrom", namespaces=NS):
            raise SystemExit("revision-wrapper guard failed")

        revised_xml = etree.tostring(
            root, xml_declaration=True, encoding="UTF-8", standalone="yes"
        )
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
