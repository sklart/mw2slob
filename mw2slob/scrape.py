import itertools
import logging
import os
import random
import time
import itertools
from typing import Optional
from typing import Sequence
from typing import Tuple
from urllib.parse import urlparse

import couchdb

from . import convert
from . import siteinfo as si
from .reliability import SourceError, is_retryable_source_error, retry

log = logging.getLogger(__name__)


def grouper(iterable, n, fillvalue=None):
    "Collect data into fixed-length chunks or blocks"
    # grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx
    args = [iter(iterable)] * n
    return itertools.zip_longest(fillvalue=fillvalue, *args)


def mkcouch(couch_url, attempts=3, initial_delay=1.0) -> Tuple[couchdb.Database, couchdb.Database]:
    parsed_url = urlparse(couch_url)
    couch_db = parsed_url.path.lstrip("/")
    server_url = parsed_url.scheme + "://" + parsed_url.netloc
    def connect():
        server = couchdb.Server(server_url)
        return server[couch_db], server["siteinfo"]

    return retry(connect, attempts=attempts, initial_delay=initial_delay)


def iter_view_with_retries(couch, view_name, batch_size, view_args,
                           attempts=3, initial_delay=1.0, sleep=time.sleep,
                           random_value=random.random):
    """Yield a CouchDB view exactly once per document across reconnects."""
    last_key = None
    seen_keys = set()
    failures = 0
    while True:
        request_args = dict(view_args)
        if last_key is not None and "keys" not in request_args:
            request_args["startkey"] = last_key
        try:
            for row in couch.iterview(view_name, batch_size, **request_args):
                row_key = row.id
                if row_key in seen_keys:
                    continue
                seen_keys.add(row_key)
                last_key = row_key
                failures = 0
                yield row
            return
        except KeyboardInterrupt:
            raise
        except Exception as error:
            failures += 1
            if not is_retryable_source_error(error) or failures >= attempts:
                raise SourceError("CouchDB view failed after {} attempts: {}".format(
                    failures, error)) from error
            delay = initial_delay * (2 ** (failures - 1))
            sleep(delay + (delay * 0.25 * random_value()))


def articles(
    couch_url: str,
    info: si.Info,
    startkey: Optional[str] = None,
    endkey: Optional[str] = None,
    key: Optional[str] = None,
    key_file: Optional[str] = None,
    langlinks: Optional[Sequence[str]] = None,
    html_encoding="utf-8",
    remove_embedded_bg="",
    ensure_ext_image_urls=True,
):

    couch, _ = mkcouch(couch_url)

    basic_view_args = {"stale": "ok", "include_docs": True}
    view_args = dict(basic_view_args)
    if startkey:
        view_args["startkey"] = startkey
    if endkey:
        view_args["endkey"] = endkey
    if key:
        view_args["keys"] = key

    def mk_params(title, aliases, text):
        return convert.ConvertParams(
            title=title,
            aliases=aliases,
            text=text,
            rtl=info.rtl,
            server=info.server,
            articlepath=info.articlepath,
            site_articlepath=info.articlepath,
            encoding=html_encoding,
            remove_embedded_bg=remove_embedded_bg,
            ensure_ext_image_urls=ensure_ext_image_urls,
        )

    def articles_from_viewiter(viewiter):
        for row in viewiter:
            if row and row.doc:
                try:
                    aliases = set()
                    for alias in row.doc.get("aliases", ()):
                        if isinstance(alias, list):
                            alias = tuple(alias)
                        aliases.add(alias)
                    if langlinks:
                        doc_langlinks = row.doc["parse"].get("langlinks", ())
                        for doc_langlink in doc_langlinks:
                            ll_lang = doc_langlink.get("lang")
                            ll_title = doc_langlink.get("*")
                            if ll_lang and ll_lang in langlinks and ll_title:
                                aliases.add(ll_title)
                    result = mk_params(
                        title=row.id,
                        aliases=aliases,
                        text=row.doc["parse"]["text"]["*"],
                    )
                except KeyboardInterrupt:
                    raise
                except Exception:
                    log.exception(repr(row.doc))
                    result = mk_params(
                        title=row.id,
                        aliases=(),
                        text=None,
                    )
                yield result

    if key_file:
        with open(os.path.expanduser(key_file)) as f:
            for key_group in grouper(
                (line.strip().replace("_", " ") for line in f if line), 50
            ):
                query_args = dict(basic_view_args)
                query_args["keys"] = [key for key in key_group if key]
                keys_found = set()
                viewiter = iter_view_with_retries(
                    couch, "_all_docs", len(query_args["keys"]), query_args
                )
                for item in articles_from_viewiter(viewiter):
                    keys_found.add(item.title)
                    yield item
                for key in set(query_args["keys"]) - keys_found:
                    yield mk_params(
                        title=key,
                        aliases=(),
                        text=None,
                    )
                keys_found.clear()

    else:
        viewiter = iter_view_with_retries(couch, "_all_docs", 50, view_args)
        for item in articles_from_viewiter(viewiter):
            yield item


def get_outname(args):
    outname = args.output_file
    if outname is None:
        basename = os.path.basename(args.couch_url)
        noext, _ = os.path.splitext(basename)
        outname = os.path.extsep.join((noext, "slob"))
    return outname


def get_siteinfo(args):
    couch, siteinfo_couch = mkcouch(args.couch_url)
    return siteinfo_couch[couch.name]
