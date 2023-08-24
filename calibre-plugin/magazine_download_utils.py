#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#

import xml.etree.ElementTree as ET
from mimetypes import guess_type
from pathlib import Path
from typing import Dict, Optional

from .libby.client import LibbyClient, LibbyFormats
from .overdrive import OverDriveClient

MIMETYPE_MAP = {
    ".xhtml": "application/xhtml+xml",
    ".html": "text/html",
    ".css": "text/css",
    ".png": "image/png",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".otf": "font/otf",
    ".ttf": "font/ttf",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".eot": "application/vnd.ms-fontobject",
    ".svg": "image/svg+xml",
    ".ncx": "application/x-dtbncx+xml",
}


def guess_mimetype(url: str) -> Optional[str]:
    """
    Attempt to guess the mimetype for a given url

    :param url:
    :return:
    """
    url_path = Path(url)
    mime_type, _ = guess_type(url_path.name, strict=False)
    if not mime_type:
        mime_type = MIMETYPE_MAP.get(url_path.suffix.lower(), None)
    return mime_type


def build_opf_package(
    media_info: Dict, version: str = "2.0", loan_format: str = LibbyFormats.AudioBookMP3
) -> ET.Element:
    """
    Build the package element from media_info.

    :param media_info:
    :param version:
    :param loan_format:
    :return:
    """

    # References:
    # Version 2: https://idpf.org/epub/20/spec/OPF_2.0_final_spec.html#Section2.0
    # Version 3: https://www.w3.org/TR/epub-33/#sec-package-doc
    direct_epub_formats = [LibbyFormats.EBookOverdrive, LibbyFormats.MagazineOverDrive]
    ET.register_namespace("opf", "http://www.idpf.org/2007/opf")
    ET.register_namespace("dc", "http://purl.org/dc/elements/1.1/")
    package = ET.Element(
        "package",
        attrib={
            "version": version,
            "xmlns": "http://www.idpf.org/2007/opf",
            "unique-identifier": "publication-id",
        },
    )
    metadata = ET.SubElement(
        package,
        "metadata",
        attrib={
            "xmlns:dc": "http://purl.org/dc/elements/1.1/",
            "xmlns:opf": "http://www.idpf.org/2007/opf",
        },
    )
    title = ET.SubElement(metadata, "dc:title")
    title.text = media_info["title"]
    if loan_format == LibbyFormats.MagazineOverDrive and media_info.get("edition"):
        # for magazines, put the edition into the title to ensure some uniqueness
        title.text = f'{media_info["title"]} - {media_info["edition"]}'

    if version == "3.0":
        title.set("id", "main-title")
        meta_main_title = ET.SubElement(
            metadata,
            "meta",
            attrib={"refines": "#main-title", "property": "title-type"},
        )
        meta_main_title.text = "main"

    if (
        version == "2.0"
        and loan_format not in direct_epub_formats
        and media_info.get("subtitle")
    ):
        ET.SubElement(metadata, "dc:subtitle").text = media_info["subtitle"]
    if version == "3.0" and media_info.get("subtitle"):
        sub_title = ET.SubElement(metadata, "dc:title")
        sub_title.text = media_info["subtitle"]
        sub_title.set("id", "sub-title")
        meta_sub_title = ET.SubElement(
            metadata, "meta", attrib={"refines": "#sub-title", "property": "title-type"}
        )
        meta_sub_title.text = "subtitle"

    if version == "3.0" and media_info.get("edition"):
        sub_title = ET.SubElement(metadata, "dc:title")
        sub_title.text = media_info["edition"]
        sub_title.set("id", "edition")
        media_edition = ET.SubElement(
            metadata, "meta", attrib={"refines": "#edition", "property": "title-type"}
        )
        media_edition.text = "edition"

    ET.SubElement(metadata, "dc:language").text = media_info["languages"][0]["id"]
    identifier = ET.SubElement(metadata, "dc:identifier")
    identifier.set("id", "publication-id")

    isbn = OverDriveClient.extract_isbn(
        media_info["formats"], format_types=[loan_format]
    )
    if isbn:
        identifier.text = isbn
        if version == "2.0":
            identifier.set("opf:scheme", "ISBN")
        if version == "3.0":
            if len(isbn) in (10, 13):
                meta_isbn = ET.SubElement(
                    metadata,
                    "meta",
                    attrib={
                        "refines": "#publication-id",
                        "property": "identifier-type",
                        "scheme": "onix:codelist5",
                    },
                )
                # https://ns.editeur.org/onix/en/5
                meta_isbn.text = "15" if len(isbn) == 13 else "02"
    else:
        identifier.text = media_info["id"]
        if version == "2.0":
            identifier.set("opf:scheme", "overdrive")
        if version == "3.0":
            identifier.text = media_info["id"]

    asin = OverDriveClient.extract_asin(media_info["formats"])
    if asin:
        asin_tag = ET.SubElement(metadata, "dc:identifier")
        asin_tag.text = asin
        asin_tag.set("id", "asin")
        if version == "2.0":
            asin_tag.set("opf:scheme", "ASIN")
        if version == "3.0":
            asin_tag_meta = ET.SubElement(
                metadata,
                "meta",
                attrib={
                    "refines": "#asin",
                    "property": "identifier-type",
                },
            )
            asin_tag_meta.text = "ASIN"

    # add overdrive id and reserveId
    overdrive_id = ET.SubElement(metadata, "dc:identifier")
    overdrive_id.text = media_info["id"]
    overdrive_id.set("id", "overdrive-id")
    overdrive_reserve_id = ET.SubElement(metadata, "dc:identifier")
    overdrive_reserve_id.text = media_info["reserveId"]
    overdrive_reserve_id.set("id", "overdrive-reserve-id")
    if version == "2.0":
        overdrive_id.set("opf:scheme", "OverDriveId")
        overdrive_reserve_id.set("opf:scheme", "OverDriveReserveId")
    if version == "3.0":
        overdrive_id_meta = ET.SubElement(
            metadata,
            "meta",
            attrib={
                "refines": "#overdrive-id",
                "property": "identifier-type",
            },
        )
        overdrive_id_meta.text = "overdrive-id"

        overdrive_reserve_id_meta = ET.SubElement(
            metadata,
            "meta",
            attrib={
                "refines": "#overdrive-reserve-id",
                "property": "identifier-type",
            },
        )
        overdrive_reserve_id_meta.text = "overdrive-reserve-id"

    # for magazines, no creators are provided, so we'll patch in the publisher
    if media_info.get("publisher", {}).get("name") and not media_info["creators"]:
        media_info["creators"] = [
            {
                "name": media_info["publisher"]["name"],
                "id": media_info["publisher"]["id"],
                "role": "Publisher",
            }
        ]

    # Roles https://idpf.org/epub/20/spec/OPF_2.0_final_spec.html#Section2.2.6
    for media_role, opf_role in (
        ("Author", "aut"),
        ("Narrator", "nrt"),
        ("Editor", "edt"),
        ("Translator", "trl"),
        ("Illustrator", "ill"),
        ("Photographer", "pht"),
        ("Artist", "art"),
        ("Collaborator", "clb"),
        ("Other", "oth"),
        ("Publisher", "pbl"),
    ):
        creators = [
            c for c in media_info["creators"] if c.get("role", "") == media_role
        ]
        for c in creators:
            creator = ET.SubElement(metadata, "dc:creator")
            creator.text = c["name"]
            if version == "2.0":
                creator.set("opf:role", opf_role)
                if c.get("sortName"):
                    creator.set("opf:file-as", c["sortName"])
            if version == "3.0":
                creator.set("id", f'creator_{c["id"]}')
                if c.get("sortName"):
                    meta_file_as = ET.SubElement(
                        metadata,
                        "meta",
                        attrib={
                            "refines": f'#creator_{c["id"]}',
                            "property": "file-as",
                        },
                    )
                    meta_file_as.text = c["sortName"]
                meta_role = ET.SubElement(
                    metadata,
                    "meta",
                    attrib={
                        "refines": f'#creator_{c["id"]}',
                        "property": "role",
                        "scheme": "marc:relators",
                    },
                )
                meta_role.text = opf_role

    if media_info.get("publisher", {}).get("name"):
        ET.SubElement(metadata, "dc:publisher").text = media_info["publisher"]["name"]
    if media_info.get("description"):
        ET.SubElement(metadata, "dc:description").text = media_info["description"]
    for s in media_info.get("subject", []):
        ET.SubElement(metadata, "dc:subject").text = s["name"]

    if version == "2.0" and loan_format not in direct_epub_formats:
        for k in media_info.get("keywords", []):
            ET.SubElement(metadata, "dc:tag").text = k
    if version == "3.0" and media_info.get("bisac"):
        for i, bisac in enumerate(media_info["bisac"], start=1):
            subject = ET.SubElement(metadata, "dc:subject")
            subject.text = bisac["description"]
            subject.set("id", f"subject_{i}")
            meta_subject_authority = ET.SubElement(
                metadata,
                "meta",
                attrib={"refines": f"#subject_{i}", "property": "authority"},
            )
            meta_subject_authority.text = "BISAC"
            meta_subject_term = ET.SubElement(
                metadata,
                "meta",
                attrib={"refines": f"#subject_{i}", "property": "term"},
            )
            meta_subject_term.text = bisac["code"]

    publish_date = media_info.get("publishDate") or media_info.get(
        "estimatedReleaseDate"
    )
    if publish_date:
        pub_date = ET.SubElement(metadata, "dc:date")
        if version == "2.0":
            pub_date.set("opf:event", "publication")
        pub_date.text = publish_date
        if version == "3.0":
            meta_pubdate = ET.SubElement(metadata, "meta")
            meta_pubdate.set("property", "dcterms:modified")
            meta_pubdate.text = publish_date

    if (
        media_info.get("detailedSeries")
        or media_info.get("series")
        or loan_format == LibbyFormats.MagazineOverDrive
    ):
        series_info = media_info.get("detailedSeries", {})
        series_name = (
            series_info.get("seriesName")
            or media_info.get("series")
            or (
                media_info["title"]
                if loan_format == LibbyFormats.MagazineOverDrive
                else None
            )
        )
        if series_name:
            ET.SubElement(
                metadata,
                "meta",
                attrib={"name": "calibre:series", "content": series_name},
            )
            if version == "3.0":
                meta_series = ET.SubElement(
                    metadata,
                    "meta",
                    attrib={"id": "series-name", "property": "belongs-to-collection"},
                )
                meta_series.text = series_name
                meta_series_type = ET.SubElement(
                    metadata,
                    "meta",
                    attrib={"refines": "#series-name", "property": "collection-type"},
                )
                meta_series_type.text = "series"

        reading_order = series_info.get("readingOrder", "")
        if (
            (not reading_order)
            and loan_format == LibbyFormats.MagazineOverDrive
            and media_info.get("estimatedReleaseDate")
        ):
            est_release_date = LibbyClient.parse_datetime(
                media_info["estimatedReleaseDate"]
            )
            reading_order = f"{est_release_date:%y%j}"  # use release date to construct a pseudo reading order

        if reading_order:
            ET.SubElement(
                metadata,
                "meta",
                attrib={
                    "name": "calibre:series_index",
                    "content": reading_order,
                },
            )
            if version == "3.0":
                meta_series_pos = ET.SubElement(
                    metadata,
                    "meta",
                    attrib={"refines": "#series-name", "property": "group-position"},
                )
                meta_series_pos.text = reading_order

    return package
