# Third-party software and materials

Home Finance Cockpit 1.0.0 — application author: Łukasz Kozłowski.

Copyright and license notices for bundled dependencies are preserved verbatim
under `licenses/third-party/`. `dependencies.json` records the exact resolved
package versions and locations of their notices. These libraries are not authored
by Łukasz Kozłowski.

| Component | Role | Licensing information |
| --- | --- | --- |
| Python 3.12.10 | Embedded interpreter and standard library | PSF license and bundled third-party notices; licenses/PYTHON.txt |
| PyQt6, PyQt6-sip | Python Qt bindings | GPLv3 distribution; original package notices |
| Qt 6.11.0 | GUI, SVG, networking, plugins and Polish translations | Applicable LGPL/GPL and third-party notices; Qt source archives and licenses/qt/ |
| Matplotlib and DejaVu fonts | Charts and PDF fonts | Original Matplotlib, DejaVu and other bundled asset licenses |
| NumPy and its bundled numeric libraries | Numeric calculations | Original NumPy/OpenBLAS notices and runtime library license exceptions |
| ReportLab | PDF generation | Original ReportLab notices and bundled font notices |
| openpyxl, et_xmlfile | Excel reading | Original MIT license notices |
| sqlcipher3 | SQLite Python adapter | Original adapter license; SQLCipher engine and crypto notices below |
| SQLCipher | Encrypted local databases | Zetetic BSD-style license; licenses/SQLCIPHER.txt |
| OpenSSL | SQLCipher cryptography | Apache-2.0 for the packaged OpenSSL 3.x build; licenses/OPENSSL.txt |
| Pillow and remaining runtime packages | Image, parsing and plotting support | Original package licenses and nested notices |
| cx-Freeze / freeze-core | Packaging and embedded executable startup | Original licenses retained; no development installation is needed on the target PC |
| Microsoft Visual C++ runtime | Native runtime DLLs | Microsoft redistributable terms; licenses/MSVC-REDIST.txt |

Only modules required by the packaged application are intended to be bundled.
The inventory also lists build tools so the release process can be reproduced;
their presence in the inventory does not mean every tool is shipped at runtime.

## Application graphics

The Home Finance Cockpit branding was supplied by the project owner and is included
as project material under GPLv3. Its original provenance cannot be independently
established from this repository. The distributor must confirm that they have the
rights to redistribute those supplied images and SVGs before public publication.
Simple interface icons are stored as editable SVG path data in the application;
no separate commercial icon pack is required to run the program.

## Scope

These notices document the release contents; they do not replace any upstream
license. Read the accompanying originals for the applicable terms. Source packages
and the upstream source manifest accompany the release. This release makes no claim
of an independent legal certification, penetration test or security audit.
