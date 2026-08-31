#!/usr/bin/env python3
"""Apply the established bounded clean-only finalizer for ZDP02l."""

from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import ZipFile
import argparse
import os

from lxml import etree


DEFAULT_DOCX = Path("Rev/revision/ZDP02l.rev.clean.docx")
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
NS = {"w": W, "m": M, "w14": W14}
SUPERSEDED_TITLE = (
    "Table 3. Adjusted rural-residence associations with economic-security outcomes"
)
REPLACEMENT_TITLE = (
    "Table 3. Adjusted rural-residence associations with first-stage pathway outcomes"
)
POLICY_FIRST_PARA_ID = "5401AE73"
POLICY_SECOND_PARA_ID = "5F8E4ADE"
POLICY_FIRST_TEXT = (
    "Economic security is policy-relevant because rural residence is associated with lower "
    "Income Security Feelings and within-place income rank, and the Income Security Feelings "
    "indirect pathway has an interval excluding zero. These associations suggest that locally "
    "appropriate efforts to reduce financial precarity may be relevant, but the cross-sectional "
    "analysis cannot establish that any specific intervention will increase life satisfaction. "
    "Policy design should therefore be guided by local evidence on employment, financial "
    "resources, and social protection rather than by a universal prescription."
)
POLICY_SECOND_TEXT = (
    "The results do not show that stronger rural social capital eliminated a disadvantage or "
    "acted as a buffer: rural residence is not precisely associated with the Social Capital "
    "Index, and the Social Capital Index indirect interval includes zero. Community-oriented "
    "initiatives may still be valuable where locally supported, but they should not be presented "
    "as a mechanism proven by these data. More generally, the observed cross-place heterogeneity "
    "argues for context-specific rather than uniform rural policy responses."
)


def normalized_text(node: etree._Element) -> str:
    return " ".join("".join(node.xpath(".//w:t/text()", namespaces=NS)).split())


def exact_text(node: etree._Element) -> str:
    return "".join(node.xpath(".//w:t/text()", namespaces=NS))


def merge_policy_paragraphs(root: etree._Element) -> None:
    first = root.xpath(
        f".//w:p[@w14:paraId='{POLICY_FIRST_PARA_ID}']", namespaces=NS
    )
    second = root.xpath(
        f".//w:p[@w14:paraId='{POLICY_SECOND_PARA_ID}']", namespaces=NS
    )
    if len(first) != 1 or len(second) != 1:
        raise SystemExit(
            f"policy paragraph guard failed: first={len(first)}, second={len(second)}"
        )
    first_para, second_para = first[0], second[0]
    parent = first_para.getparent()
    if parent is None or second_para.getparent() is not parent:
        raise SystemExit("policy paragraph parent guard failed")
    if parent.index(second_para) != parent.index(first_para) + 1:
        raise SystemExit("policy paragraph adjacency guard failed")
    if exact_text(first_para) != POLICY_FIRST_TEXT + " ":
        raise SystemExit("policy first-paragraph text guard failed")
    if exact_text(second_para) != POLICY_SECOND_TEXT:
        raise SystemExit("policy second-paragraph text guard failed")
    for child in list(second_para):
        if child.tag != f"{{{W}}}pPr":
            first_para.append(child)
    parent.remove(second_para)
    if exact_text(first_para) != POLICY_FIRST_TEXT + " " + POLICY_SECOND_TEXT:
        raise SystemExit("policy merged-paragraph verification failed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", nargs="?", type=Path, default=DEFAULT_DOCX)
    args = parser.parse_args()
    docx = args.docx
    with ZipFile(docx, "r") as source:
        root = etree.fromstring(source.read("word/document.xml"))
        merge_policy_paragraphs(root)
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
            prefix=f".{docx.name}.", suffix=".tmp", dir=docx.parent, delete=False
        ) as handle:
            staged_path = Path(handle.name)

        try:
            with ZipFile(staged_path, "w") as staged:
                for info in source.infolist():
                    payload = revised_xml if info.filename == "word/document.xml" else source.read(info.filename)
                    staged.writestr(info, payload)
            os.replace(staged_path, docx)
        finally:
            staged_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
