import zipfile
from pathlib import Path
from xml.etree import ElementTree

WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


class LegacyDocumentError(ValueError):
    pass


def read_docx_text(path: Path) -> str:
    """Extract visible paragraph text from a DOCX using only the standard library."""
    try:
        with zipfile.ZipFile(path) as document:
            xml = document.read("word/document.xml")
        root = ElementTree.fromstring(xml)
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise LegacyDocumentError(f"cannot read DOCX: {path.name}") from exc

    namespace = {"w": WORD_NAMESPACE}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        parts: list[str] = []
        for element in paragraph.iter():
            if element.tag == f"{{{WORD_NAMESPACE}}}t" and element.text:
                parts.append(element.text)
            elif element.tag == f"{{{WORD_NAMESPACE}}}tab":
                parts.append("\t")
            elif element.tag in {
                f"{{{WORD_NAMESPACE}}}br",
                f"{{{WORD_NAMESPACE}}}cr",
            }:
                parts.append("\n")
        paragraphs.append("".join(parts))
    return "\n".join(paragraphs).strip()
