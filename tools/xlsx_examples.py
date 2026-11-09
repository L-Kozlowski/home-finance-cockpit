"""Small standard-library XLSX writer for static, synthetic example workbooks.

No formulas/macros or runtime Excel dependency. Strings are explicit inline strings.
"""

from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def column_name(number):
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def write_xlsx(path, sheets):
    """Sheets: iterable of (name, rows, widths); first row is the header."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content_types = [
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
    ]
    workbook, relationships = [], []
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for index, (name, rows, widths) in enumerate(sheets, 1):
            name = escape(name, {'"': "&quot;"})
            workbook.append(f'<sheet name="{name}" sheetId="{index}" r:id="rId{index}"/>')
            relationships.append(
                f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
            )
            content_types.append(
                f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )
            cells = []
            for row_number, row in enumerate(rows, 1):
                values = []
                for column, value in enumerate(row, 1):
                    address = column_name(column) + str(row_number)
                    style = (
                        ' s="1"'
                        if row_number == 1
                        else ' s="2"'
                        if isinstance(value, Decimal)
                        else ""
                    )
                    if value is None:
                        values.append(f'<c r="{address}"{style}/>')
                    elif isinstance(value, (int, Decimal)) and not isinstance(value, bool):
                        values.append(f'<c r="{address}"{style}><v>{value}</v></c>')
                    else:
                        values.append(
                            f'<c r="{address}"{style} t="inlineStr"><is><t xml:space="preserve">{escape(str(value))}</t></is></c>'
                        )
                cells.append(f'<row r="{row_number}">' + "".join(values) + "</row>")
            columns = "".join(
                f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>'
                for i, width in enumerate(widths, 1)
            )
            last = f"{column_name(len(rows[0]))}{len(rows)}"
            archive.writestr(
                f"xl/worksheets/sheet{index}.xml",
                f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{NS}"><dimension ref="A1:{last}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>{columns}</cols><sheetData>{"".join(cells)}</sheetData><autoFilter ref="A1:{last}"/></worksheet>',
            )
        relationships.append(
            '<Relationship Id="styles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        )
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            + "".join(content_types)
            + "</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{"".join(workbook)}</sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(relationships)
            + "</Relationships>",
        )
        archive.writestr(
            "xl/styles.xml",
            f'<styleSheet xmlns="{NS}"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF112233"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFill="1" applyFont="1"/><xf numFmtId="4" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>',
        )
