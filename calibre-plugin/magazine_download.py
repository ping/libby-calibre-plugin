#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#

import base64
import os
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from functools import cmp_to_key
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup, Doctype, Tag, element
from calibre.gui2.ebook_download import EbookDownload
from calibre.ptempfile import PersistentTemporaryDirectory

from .libby import LibbyClient
from .libby.client import LibbyMediaTypes, LibbyFormats
from .magazine_download_utils import (
    get_best_cover_url,
    guess_mimetype,
    extract_isbn,
    slugify,
    is_windows,
    build_opf_package,
)
from .overdrive.client import OverDriveClient

NAV_XHTMLTEMPLATE = """
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title></title>
<style>
    #toc { list-style-type: none; padding-left: 0; }
    #toc > li { margin-top: 0.5rem; }
</style>
</head>
<body>
<nav epub:type="toc">
<h1>Contents</h1>
<ol id="toc"></ol>
</nav>
</body>
</html>
"""


def _sort_toc(toc: Dict) -> List:
    """
    Sorts the ToC dict from openbook into a hierarchical structure

    :param toc:
    :return:
    """
    hierarchical_toc = []
    current_section = {}  # type: Dict
    for i, item in enumerate(toc, start=1):
        if not item.get("sectionName"):
            hierarchical_toc.append(item)
            continue
        if item["sectionName"] not in current_section or i == len(toc):
            # new section or last item
            if i == len(toc):
                current_section.setdefault(item["sectionName"], []).append(item)
            section_names = list(current_section.keys())
            for section_name in section_names:
                hierarchical_toc.append(
                    {
                        "sectionName": section_name,
                        "items": current_section[section_name],
                    }
                )
                del current_section[section_name]
        if i < len(toc):
            current_section.setdefault(item["sectionName"], []).append(item)

    return hierarchical_toc


def _build_ncx(media_info: Dict, openbook: Dict, nav_page: str) -> ET.Element:
    """
    Build the ncx from openbook

    :param media_info:
    :param openbook:
    :param nav_page:
    :return:
    """

    # References:
    # Version 2: https://idpf.org/epub/20/spec/OPF_2.0_final_spec.html#Section2.0
    # Version 3: https://www.w3.org/TR/epub-33/#sec-package-doc

    publication_identifier = (
        extract_isbn(
            media_info["formats"],
            [LibbyFormats.EBookOverdrive, LibbyFormats.MagazineOverDrive],
        )
        or media_info["id"]
    )

    ET.register_namespace("opf", "http://www.idpf.org/2007/opf")
    ET.register_namespace("dc", "http://purl.org/dc/elements/1.1/")
    ncx = ET.Element(
        "ncx",
        attrib={
            "version": "2005-1",
            "xmlns": "http://www.daisy.org/z3986/2005/ncx/",
            "xml:lang": "en",
        },
    )

    head = ET.SubElement(ncx, "head")
    ET.SubElement(
        head, "meta", attrib={"content": publication_identifier, "name": "dtb:uid"}
    )
    doc_title = ET.SubElement(ncx, "docTitle")
    doc_title_text = ET.SubElement(doc_title, "text")
    doc_title_text.text = openbook["title"]["main"]

    doc_author = ET.SubElement(ncx, "docAuthor")
    doc_author_text = ET.SubElement(doc_author, "text")
    doc_author_text.text = openbook["creator"][0]["name"]

    nav_map = ET.SubElement(ncx, "navMap")
    hierarchical_toc = _sort_toc(openbook["nav"]["toc"])
    nav_point_counter = 0
    for item in hierarchical_toc:
        nav_point_counter += 1
        if not item.get("sectionName"):
            nav_point = ET.SubElement(
                nav_map, "navPoint", attrib={"id": f"navPoint{nav_point_counter}"}
            )
            nav_label = ET.SubElement(nav_point, "navLabel")
            nav_label_text = ET.SubElement(nav_label, "text")
            nav_label_text.text = item["title"]
            ET.SubElement(nav_point, "content", attrib={"src": item["path"]})

            if nav_point_counter == 1 and nav_page:
                nav_point_counter += 1
                nav_point = ET.SubElement(
                    nav_map, "navPoint", attrib={"id": f"navPoint{nav_point_counter}"}
                )
                nav_label = ET.SubElement(nav_point, "navLabel")
                nav_label_text = ET.SubElement(nav_label, "text")
                nav_label_text.text = "Contents"
                ET.SubElement(nav_point, "content", attrib={"src": nav_page})
            continue

        nav_point = ET.SubElement(
            nav_map, "navPoint", attrib={"id": f"navPoint{nav_point_counter}"}
        )
        nav_label = ET.SubElement(nav_point, "navLabel")
        nav_label_text = ET.SubElement(nav_label, "text")
        nav_label_text.text = item["sectionName"]
        # since we don't have a section content page, link section to first article path
        ET.SubElement(nav_point, "content", attrib={"src": item["items"][0]["path"]})
        for section_item in item["items"]:
            nav_point_counter += 1
            section_item_nav_point = ET.SubElement(
                nav_point, "navPoint", attrib={"id": f"navPoint{nav_point_counter}"}
            )
            section_item_nav_label = ET.SubElement(section_item_nav_point, "navLabel")
            section_item_nav_label_text = ET.SubElement(section_item_nav_label, "text")
            section_item_nav_label_text.text = section_item["title"]
            ET.SubElement(
                section_item_nav_point, "content", attrib={"src": section_item["path"]}
            )
    return ncx


def _sanitise_opf_id(string_id: str) -> str:
    """
    OPF IDs cannot start with a number
    :param string_id:
    :return:
    """
    string_id = slugify(string_id)
    if string_id[0].isdigit():
        return f"id_{string_id}"
    return string_id


def _cleanup_soup(soup: BeautifulSoup, version: str = "2.0") -> None:
    """
    Tries to fix up book content pages to be epub-version compliant.

    :param soup:
    :param version:
    :return:
    """
    if version == "2.0":
        # v2 is a lot pickier about the acceptable elements and attributes
        modified_doctype = 'html PUBLIC "-//W3C//DTD XHTML 1.1//EN" "http://www.w3.org/TR/xhtml11/DTD/xhtml11.dtd"'
        for item in soup.contents:
            if isinstance(item, Doctype):
                item.replace_with(Doctype(modified_doctype))
                break
        remove_attributes = [
            # this list will not be complete, but we try
            "aria-label",
            "data-loc",
            "data-epub-type",
            "data-document-status",
            "data-xml-lang",
            "lang",
            "role",
            "epub:type",
            "epub:prefix",
        ]
        for attribute in remove_attributes:
            for tag in soup.find_all(attrs={attribute: True}):
                del tag[attribute]
        convert_tags = ["nav", "section"]  # this list will not be complete, but we try
        for tag in convert_tags:
            for invalid_tag in soup.find_all(tag):
                invalid_tag.name = "div"

    # known issues, this will not be complete
    for svg in soup.find_all("svg"):
        if not svg.get("xmlns"):
            svg["xmlns"] = "http://www.w3.org/2000/svg"
        if not svg.get("xmlns:xlink"):
            svg["xmlns:xlink"] = "http://www.w3.org/1999/xlink"
    convert_tags = ["figcaption"]
    for tag in convert_tags:
        for invalid_tag in soup.find_all(tag):
            invalid_tag.name = "div"
    remove_tags = ["base"]
    for tag in remove_tags:
        for remove_tag in soup.find_all(tag):
            remove_tag.decompose()

    html_tag = soup.find("html")
    if html_tag and isinstance(html_tag, element.Tag) and not html_tag.get("xmlns"):
        html_tag["xmlns"] = "http://www.w3.org/1999/xhtml"


def _sort_spine_entries(a: Dict, b: Dict, toc_pages: List[str]):
    """
    Sort spine according to TOC. For magazines, this is sometimes a
    problem where the sequence laid out in the spine does not align
    with the TOC, e.g. Mother Jones. If unsorted, the page through
    sequence does not match the actual TOC.

    :param a:
    :param b:
    :param toc_pages:
    :return:
    """
    try:
        a_index = toc_pages.index(a["-odread-original-path"])
    except ValueError:
        a_index = 999
    try:
        b_index = toc_pages.index(b["-odread-original-path"])
    except ValueError:
        b_index = 999

    if a_index != b_index:
        # sort order found via toc
        return -1 if a_index < b_index else 1

    return -1 if a["-odread-spine-position"] < b["-odread-spine-position"] else 1


def _sort_title_contents(a: Dict, b: Dict):
    """
    Sort the title contents roster so that pages get processed first.
    This is a precautionary measure for getting high-res cover images
    since we must parse the html for the image src.

    :param a:
    :param b:
    :return:
    """
    extensions_rank = [
        ".xhtml",
        ".html",
        ".htm",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".ttf",  # download fonts before css so that we can check if font is available
        ".otf",
        ".css",
    ]
    a_parsed_url = urlparse(a["url"])
    b_parsed_url = urlparse(b["url"])
    a_ext = Path(a_parsed_url.path).suffix
    b_ext = Path(b_parsed_url.path).suffix
    try:
        a_index = extensions_rank.index(a_ext)
    except ValueError:
        a_index = 999
    try:
        b_index = extensions_rank.index(b_ext)
    except ValueError:
        b_index = 999

    if a_index != b_index:
        # sort order found via toc
        return -1 if a_index < b_index else 1

    if a_ext != b_ext:
        return -1 if a_ext < b_ext else 1

    return -1 if a_parsed_url.path < b_parsed_url.path else 1


def _filter_content(entry: Dict, media_info: Dict, toc_pages: List[str]):
    """
    Filter title contents that are not needed.

    :param entry:
    :param media_info:
    :param toc_pages:
    :return:
    """
    parsed_entry_url = urlparse(entry["url"])
    media_type = guess_mimetype(parsed_entry_url.path[1:])

    if media_info["type"]["id"] == LibbyMediaTypes.Magazine and media_type:
        if media_type.startswith("image/") and (
            parsed_entry_url.path.startswith("/pages/")
            or parsed_entry_url.path.startswith("/thumbnails/")
        ):
            return False
        if (
            media_type in ("application/xhtml+xml", "text/html")
            and parsed_entry_url.path[1:] not in toc_pages
        ):
            return False

    if parsed_entry_url.path.startswith("/_d/"):  # ebooks
        return False

    return True


# Ref: https://github.com/kovidgoyal/calibre/blob/58c609fa7db3a8df59981c3bf73823fa1862c392/src/calibre/gui2/ebook_download.py#L77-L122
class CustomMagazineDownload(EbookDownload):
    def __call__(
        self,
        gui,
        libby_client: LibbyClient,
        loan: Dict,
        format_id: str,
        cookie_file=None,
        url="",
        filename="",
        save_loc="",
        add_to_lib=True,
        tags=[],
        create_browser=None,
        log=None,
        abort=None,
        notifications=None,
    ):
        dfilename = ""
        try:
            dfilename = self._custom_download(
                libby_client, loan, format_id, filename, log, abort, notifications
            )
            self._add(dfilename, gui, add_to_lib, tags)
            self._save_as(dfilename, save_loc)
        finally:
            try:
                if dfilename:
                    os.remove(dfilename)
            except:
                pass

    def _custom_download(
        self,
        libby_client: LibbyClient,
        loan: Dict,
        format_id: str,
        filename: str,
        log=None,
        abort=None,
        notifications=None,
    ):
        logger = log
        download_progress_fraction = 0.97
        meta_progress_fraction = 1.0 - download_progress_fraction
        meta_tasks = 3

        book_folder = Path(PersistentTemporaryDirectory())
        epub_file_path = book_folder.joinpath(filename)
        epub_version = "3.0"

        notifications.put(
            (
                (1 / meta_tasks) * meta_progress_fraction,
                "Getting loan details",
            )
        )
        _, openbook, rosters = libby_client.process_ebook(loan)
        cover_url = get_best_cover_url(loan)
        cover_path = book_folder.joinpath("cover.jpg")
        try:
            notifications.put(
                (
                    (2 / meta_tasks) * meta_progress_fraction,
                    "Downloading cover",
                )
            )
            with cover_path.open("w+b") as cover_f:
                cover_f.write(
                    libby_client.send_request(
                        cover_url, authenticated=False, decode_response=False
                    )
                )
        except:
            cover_path = None

        book_meta_name = "META-INF"
        book_content_name = "OEBPS"
        book_meta_folder = book_folder.joinpath(book_meta_name)
        book_content_folder = book_folder.joinpath(book_content_name)
        for d in (book_meta_folder, book_content_folder):
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)

        od_client = OverDriveClient(
            user_agent=libby_client.user_agent,
            timeout=libby_client.timeout,
            max_retries=libby_client.max_retries,
            logger=libby_client.logger,
        )
        notifications.put(
            (
                (3 / meta_tasks) * meta_progress_fraction,
                "Getting book details",
            )
        )
        media_info = od_client.media(loan["id"])
        title_contents: Dict = next(
            iter([r for r in rosters if r["group"] == "title-content"]), {}
        )
        headers = libby_client.default_headers()
        headers["Accept"] = "*/*"
        contents_re = re.compile(r"parent\.__bif_cfc0\(self,'(?P<base64_text>.+)'\)")

        openbook_toc = openbook["nav"]["toc"]
        if len(openbook_toc) <= 1 and loan["type"]["id"] == LibbyMediaTypes.Magazine:
            msg = "Magazine has unsupported fixed-layout (pre-paginated) format."
            logger.error(msg)
            raise Exception(msg)

        # for finding cover image for magazines
        cover_toc_item = next(
            iter(
                [
                    item
                    for item in openbook_toc
                    if item.get("pageRange", "") == "Cover" and item.get("featureImage")
                ]
            ),
            None,
        )
        # for finding cover image for ebooks
        cover_page_landmark = next(
            iter(
                [
                    item
                    for item in openbook.get("nav", {}).get("landmarks", [])
                    if item["type"] == "cover"
                ]
            ),
            None,
        )
        toc_pages = [item["path"].split("#")[0] for item in openbook_toc]
        manifest_entries: List[Dict] = []
        title_content_entries = list(
            filter(
                lambda e: _filter_content(e, media_info, toc_pages),
                title_contents["entries"],
            )
        )
        # Ignoring mypy error below because of https://github.com/python/mypy/issues/9372
        title_content_entries = sorted(
            title_content_entries, key=cmp_to_key(_sort_title_contents)  # type: ignore[misc]
        )
        has_ncx = False
        has_nav = False

        # Used to patch magazine css that causes paged mode in calibre viewer to not work.
        # This expression is used to strip `overflow-x: hidden` from the css definition
        # for `#article-body`.
        patch_magazine_css_overflow_re = re.compile(
            r"(#article-body\s*\{[^{}]+?)overflow-x:\s*hidden;([^{}]+?})"
        )
        # This expression is used to strip `padding: Xem Xem;` from the css definition
        # for `#article-body` to remove the extraneous padding
        patch_magazine_css_padding_re = re.compile(
            r"(#article-body\s*\{[^{}]+?)padding:\s*[^;]+;([^{}]+?})"
        )
        # This expression is used to patch the missing fonts-specified in magazine css
        patch_magazine_css_font_re = re.compile(
            r"(font-family: '[^']+(Sans|Serif)[^']+';)"
        )
        # This expression is used to strip the missing font src in magazine css
        patch_magazine_css_font_src_re = re.compile(
            r"@font-face\s*\{[^{}]+?(src:\s*url\('(fonts/.+\.ttf)'\).+?;)[^{}]+?}"
        )

        # holds the manifest item ID for the image identified as the cover
        cover_img_manifest_id = None

        total_downloads = len(title_content_entries)

        for i, entry in enumerate(title_content_entries, start=1):
            if abort.is_set():
                msg = "Abort signal received."
                logger.info(msg)
                raise RuntimeError(msg)
            entry_url = entry["url"]
            parsed_entry_url = urlparse(entry_url)
            title_content_path = Path(parsed_entry_url.path[1:])
            logger.info(
                "Proccesing %d/%d : %s" % (i, total_downloads, title_content_path.name)
            )
            media_type = guess_mimetype(title_content_path.name)
            if not media_type:
                logger.warning("Skipped roster entry: %s" % title_content_path.name)
                continue
            asset_folder = book_content_folder.joinpath(title_content_path.parent)
            if media_type == "application/x-dtbncx+xml":
                has_ncx = True
            manifest_entry = {
                "href": parsed_entry_url.path[1:],
                "id": "ncx"
                if media_type == "application/x-dtbncx+xml"
                else _sanitise_opf_id(parsed_entry_url.path[1:]),
                "media-type": media_type,
            }

            # try to find cover image for magazines
            if cover_toc_item and manifest_entry["id"] == _sanitise_opf_id(
                cover_toc_item["featureImage"]
            ):
                # we assign it here to ensure that the image referenced in the
                # toc actually exists
                cover_img_manifest_id = manifest_entry["id"]

            if not asset_folder.exists():
                asset_folder.mkdir(parents=True, exist_ok=True)
            asset_file_path = asset_folder.joinpath(Path(parsed_entry_url.path).name)

            soup = None
            # use the libby client session because the required
            # auth cookies are set there
            res: bytes = libby_client.send_request(
                entry_url, headers=headers, authenticated=False, decode_response=False
            )
            # patch magazine css to fix various rendering problems
            if (
                media_info["type"]["id"] == LibbyMediaTypes.Magazine
                and media_type == "text/css"
            ):
                css_content = patch_magazine_css_overflow_re.sub(
                    r"\1\2", res.decode("utf-8")
                )
                css_content = patch_magazine_css_padding_re.sub(r"\1\2", css_content)
                if "#article-body" in css_content:
                    # patch font-family declarations
                    # libby declares these font-faces but does not supply them in the roster
                    # nor are they actually available when viewed online (http 403)
                    font_families = list(
                        set(patch_magazine_css_font_re.findall(css_content))
                    )
                    for font_family, _ in font_families:
                        new_font_css = font_family[:-1]
                        if "Serif" in font_family:
                            new_font_css += ',Charter,"Bitstream Charter","Sitka Text",Cambria,serif'
                        elif "Sans" in font_family:
                            new_font_css += ",system-ui,sans-serif"
                        new_font_css += ";"
                        if "-Bold" in font_family:
                            new_font_css += " font-weight: 700;"
                        elif "-SemiBold" in font_family:
                            new_font_css += " font-weight: 600;"
                        elif "-Light" in font_family:
                            new_font_css += " font-weight: 300;"
                        css_content = css_content.replace(font_family, new_font_css)
                else:
                    # patch font url declarations
                    # since ttf/otf files are downloaded ahead of css, we can verify
                    # if the font files are actually available
                    try:
                        font_sources = patch_magazine_css_font_src_re.findall(
                            css_content
                        )
                        for src_match, font_src in font_sources:
                            asset_font_path = Path(
                                urljoin(str(asset_file_path), font_src)
                            )
                            if not asset_font_path.exists():
                                css_content = css_content.replace(src_match, "")
                    except (
                        Exception  # noqa, pylint: disable=broad-exception-caught
                    ) as patch_err:
                        logger.warning(
                            "Error while patching font sources: %s" % patch_err
                        )
                with open(asset_file_path, "w", encoding="utf-8") as f_out:
                    f_out.write(css_content)
            elif media_type in ("application/xhtml+xml", "text/html"):
                soup = BeautifulSoup(res.decode("utf8"), features="html.parser")
                script_ele = soup.find("script", attrs={"type": "text/javascript"})
                if script_ele and hasattr(script_ele, "string"):
                    mobj = contents_re.search(script_ele.string or "")
                    if not mobj:
                        logger.warning(
                            "Unable to extract content string for %s"
                            % parsed_entry_url.path,
                        )
                    else:
                        new_soup = BeautifulSoup(
                            base64.b64decode(mobj.group("base64_text")),
                            features="html.parser",
                        )
                        soup.body.replace_with(new_soup.body)  # type: ignore[arg-type,union-attr]
                _cleanup_soup(soup, version=epub_version)
                if (
                    cover_toc_item
                    and cover_toc_item.get("featureImage")
                    and manifest_entry["id"] == _sanitise_opf_id(cover_toc_item["path"])
                ):
                    img_src = os.path.relpath(
                        book_content_folder.joinpath(cover_toc_item["featureImage"]),
                        start=asset_folder,
                    )
                    if is_windows():
                        img_src = Path(img_src).as_posix()
                    # patch the svg based cover for magazines
                    cover_svg = soup.find("svg")
                    if cover_svg:
                        # replace the svg ele with a simple image tag
                        cover_svg.decompose()  # type: ignore[union-attr]
                        for c in soup.body.find_all(recursive=False):  # type: ignore[union-attr]
                            c.decompose()
                        soup.body.append(  # type: ignore[union-attr]
                            soup.new_tag("img", attrs={"src": img_src, "alt": "Cover"})
                        )
                        style_ele = soup.new_tag("style")
                        style_ele.append(
                            "img { max-width: 100%; margin-left: auto; margin-right: auto; }"
                        )
                        soup.head.append(style_ele)  # type: ignore[union-attr]

                with open(asset_file_path, "w", encoding="utf-8") as f_out:
                    f_out.write(str(soup))
            else:
                with open(asset_file_path, "wb") as f_out:
                    f_out.write(res)
            notifications.put(
                (
                    (i / total_downloads) * download_progress_fraction
                    + meta_progress_fraction,
                    "Downloading",
                )
            )

            if soup:
                # try to min. soup searches where possible
                if (
                    (not cover_img_manifest_id)
                    and cover_page_landmark
                    and cover_page_landmark["path"] == parsed_entry_url.path[1:]
                ):
                    # try to find cover image for the book from the cover html content
                    cover_image = soup.find("img", attrs={"src": True})
                    if cover_image:
                        cover_img_manifest_id = _sanitise_opf_id(
                            urljoin(cover_page_landmark["path"], cover_image["src"])  # type: ignore[index]
                        )
                elif (not has_nav) and soup.find(attrs={"epub:type": "toc"}):
                    # identify nav page
                    manifest_entry["properties"] = "nav"
                    has_nav = True
                elif soup.find("svg"):
                    # page has svg
                    manifest_entry["properties"] = "svg"

            if cover_img_manifest_id == manifest_entry["id"]:
                manifest_entry["properties"] = "cover-image"
            manifest_entries.append(manifest_entry)
            if manifest_entry.get("properties") == "cover-image" and cover_path:
                # replace the cover image already downloaded via the OD api, in case it is to be kept
                shutil.copyfile(asset_file_path, cover_path)

        if not has_nav:
            # Generate nav - needed for magazines

            # we give the nav an id-stamped file name to avoid accidentally overwriting
            # an existing file name
            nav_file_name = f'nav_{loan["id"]}.xhtml'

            nav_soup = BeautifulSoup(NAV_XHTMLTEMPLATE, features="html.parser")
            nav_soup.find("title").append(loan["title"])  # type: ignore[union-attr]
            toc_ele = nav_soup.find(id="toc")

            # sort toc into hierarchical sections
            hierarchical_toc = _sort_toc(openbook_toc)
            for item in hierarchical_toc:
                li_ele = nav_soup.new_tag("li")
                if not item.get("sectionName"):
                    a_ele = nav_soup.new_tag("a", attrs={"href": item["path"]})
                    a_ele.append(item["title"])
                    li_ele.append(a_ele)
                    toc_ele.append(li_ele)  # type: ignore[union-attr]
                    continue
                # since we don't have a section content page, and this can cause problems,
                # link section to first article path
                a_ele = nav_soup.new_tag("a", attrs={"href": item["items"][0]["path"]})
                a_ele.append(item["sectionName"])
                li_ele.append(a_ele)
                ol_ele = nav_soup.new_tag("ol", attrs={"type": "1"})
                for section_item in item.get("items", []):
                    section_li_ele = nav_soup.new_tag("li")
                    section_item_a_ele = nav_soup.new_tag(
                        "a", attrs={"href": section_item["path"]}
                    )
                    section_item_a_ele.append(section_item["title"])
                    section_li_ele.append(section_item_a_ele)
                    ol_ele.append(section_li_ele)
                    continue
                li_ele.append(ol_ele)
                toc_ele.append(li_ele)  # type: ignore[union-attr]

            with book_content_folder.joinpath(nav_file_name).open(
                "w", encoding="utf-8"
            ) as f_nav:
                f_nav.write(str(nav_soup).strip())
            manifest_entries.append(
                {
                    "href": nav_file_name,
                    "id": _sanitise_opf_id(nav_file_name),
                    "media-type": "application/xhtml+xml",
                    "properties": "nav",
                }
            )

        if not has_ncx:
            # generate ncx for backward compat
            ncx = _build_ncx(media_info, openbook, nav_file_name if not has_nav else "")
            # we give the ncx an id-stamped file name to avoid accidentally overwriting
            # an existing file name
            toc_ncx_name = f'toc_{loan["id"]}.ncx'
            tree = ET.ElementTree(ncx)
            tree.write(
                book_content_folder.joinpath(toc_ncx_name),
                xml_declaration=True,
                encoding="utf-8",
            )
            manifest_entries.append(
                {
                    "href": toc_ncx_name,
                    "id": "ncx",
                    "media-type": "application/x-dtbncx+xml",
                }
            )
            has_ncx = True
        else:
            # EPUB3 compliance: Ensure that the identifier in ncx matches the one in the OPF
            # Mismatch due to the toc.ncx being supplied by publisher
            ncx_manifest_entry = next(
                iter([m for m in manifest_entries if m["id"] == "ncx"]), None
            )
            if ncx_manifest_entry:
                expected_book_identifier = (
                    extract_isbn(
                        media_info["formats"],
                        format_types=[
                            LibbyFormats.MagazineOverDrive
                            if loan["type"]["id"] == LibbyMediaTypes.Magazine
                            else LibbyFormats.EBookOverdrive
                        ],
                    )
                    or media_info["id"]
                )  # this is the summarised logic from build_opf_package
                ncx_path = book_content_folder.joinpath(ncx_manifest_entry["href"])
                new_ncx_contents = None
                with ncx_path.open("r", encoding="utf-8") as ncx_f:
                    ncx_soup = BeautifulSoup(ncx_f, features="xml")
                    meta_id = ncx_soup.find("meta", attrs={"name": "dtb:uid"})
                    if (
                        meta_id
                        and type(meta_id) == Tag
                        and meta_id.get("content")
                        and meta_id["content"] != expected_book_identifier
                    ):
                        logger.debug(
                            'Replacing identifier in %s: "%s" -> "%s"'
                            % (
                                ncx_path.name,
                                meta_id["content"],
                                expected_book_identifier,
                            )
                        )
                        meta_id["content"] = expected_book_identifier
                        new_ncx_contents = str(ncx_soup)
                if new_ncx_contents:
                    with ncx_path.open("w", encoding="utf-8") as ncx_f:
                        ncx_f.write(new_ncx_contents)

        # create epub OPF
        opf_file_name = "package.opf"
        opf_file_path = book_content_folder.joinpath(opf_file_name)
        package = build_opf_package(
            media_info,
            version=epub_version,
            loan_format=LibbyFormats.MagazineOverDrive
            if loan["type"]["id"] == LibbyMediaTypes.Magazine
            else LibbyFormats.EBookOverdrive,
        )

        # add manifest
        manifest = ET.SubElement(package, "manifest")
        for entry in manifest_entries:
            ET.SubElement(manifest, "item", attrib=entry)

        cover_manifest_entry = next(
            iter(
                [
                    entry
                    for entry in manifest_entries
                    if entry.get("properties", "") == "cover-image"
                ]
            ),
            None,
        )
        if not cover_manifest_entry:
            cover_img_manifest_id = None
        if cover_path and not cover_manifest_entry:
            # add cover image separately since we can't identify which item is the cover
            # we give the cover a timestamped file name to avoid accidentally overwriting
            # an existing file name
            cover_image_name = f"cover_{int(datetime.now().timestamp())}.jpg"
            shutil.copyfile(cover_path, book_content_folder.joinpath(cover_image_name))
            cover_img_manifest_id = "coverimage"
            ET.SubElement(
                manifest,
                "item",
                attrib={
                    "id": cover_img_manifest_id,
                    "href": cover_image_name,
                    "media-type": "image/jpeg",
                    "properties": "cover-image",
                },
            )
        if cover_img_manifest_id:
            metadata = package.find("metadata")
            if metadata:
                _ = ET.SubElement(
                    metadata,
                    "meta",
                    attrib={"name": "cover", "content": cover_img_manifest_id},
                )

        # add spine
        spine = ET.SubElement(package, "spine")
        if has_ncx:
            spine.set("toc", "ncx")
        spine_entries = list(
            filter(
                lambda s: not (
                    media_info["type"]["id"] == LibbyMediaTypes.Magazine
                    and s["-odread-original-path"] not in toc_pages
                ),
                openbook["spine"],
            )
        )

        # Ignoring mypy error below because of https://github.com/python/mypy/issues/9372
        spine_entries = sorted(
            spine_entries, key=cmp_to_key(lambda a, b: _sort_spine_entries(a, b, toc_pages))  # type: ignore[misc]
        )
        for spine_idx, entry in enumerate(spine_entries):
            if (
                media_info["type"]["id"] == LibbyMediaTypes.Magazine
                and entry["-odread-original-path"] not in toc_pages
            ):
                continue
            item_ref = ET.SubElement(spine, "itemref")
            item_ref.set("idref", _sanitise_opf_id(entry["-odread-original-path"]))
            if spine_idx == 0 and not has_nav:
                item_ref = ET.SubElement(spine, "itemref")
                item_ref.set("idref", _sanitise_opf_id(nav_file_name))

        # add guide
        if openbook.get("nav", {}).get("landmarks"):
            guide = ET.SubElement(package, "guide")
            for landmark in openbook["nav"]["landmarks"]:
                _ = ET.SubElement(
                    guide,
                    "reference",
                    attrib={
                        "href": landmark["path"],
                        "title": landmark["title"],
                        "type": landmark["type"],
                    },
                )
        tree = ET.ElementTree(package)
        tree.write(opf_file_path, xml_declaration=True, encoding="utf-8")

        # create container.xml
        container_file_path = book_meta_folder.joinpath("container.xml")
        container = ET.Element(
            "container",
            attrib={
                "version": "1.0",
                "xmlns": "urn:oasis:names:tc:opendocument:xmlns:container",
            },
        )
        root_files = ET.SubElement(container, "rootfiles")
        _ = ET.SubElement(
            root_files,
            "rootfile",
            attrib={
                # use posix path because zipFile requires "/"
                "full-path": Path(book_content_name, opf_file_name).as_posix(),
                "media-type": "application/oebps-package+xml",
            },
        )
        tree = ET.ElementTree(container)
        tree.write(container_file_path, xml_declaration=True, encoding="utf-8")
        logger.debug('Saved "%s"' % container_file_path)

        # create epub zip
        with zipfile.ZipFile(
            epub_file_path, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as epub_zip:
            epub_zip.writestr(
                "mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED
            )
            for root_start in (book_meta_folder, book_content_folder):
                for p in root_start.glob("**/*"):
                    if p.is_dir():
                        continue
                    zip_archive_file = p.relative_to(book_folder)
                    # using posix path because zipfile requires "/" separators
                    # and may break on Windows otherwise
                    zip_archive_name = zip_archive_file.as_posix()
                    zip_target_file = book_folder.joinpath(zip_archive_file)
                    epub_zip.write(zip_target_file, zip_archive_name)
                    logger.debug(
                        'epub: Added "%s" as "%s"' % (zip_target_file, zip_archive_name)
                    )
        logger.info('Saved "%s"' % epub_file_path)
        return str(epub_file_path)
