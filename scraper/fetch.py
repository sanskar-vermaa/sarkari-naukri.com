"""Fetching official pages.

Many Indian government sites serve an incomplete TLS certificate chain (the
intermediate certificate is missing), which makes normal HTTPS clients fail.
Browsers fix this by downloading the missing intermediate from the URL listed in
the certificate itself (the "AIA" extension). We do the same here, so the
connection is still fully verified — we never turn verification off.
"""
from __future__ import annotations

import os
import socket
import ssl
import tempfile
from urllib.parse import urlparse

import certifi
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
TIMEOUT = 35

_session: requests.Session | None = None
_extra_pems: dict[str, str] = {}  # host -> PEM of fetched intermediates


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        retry = Retry(total=2, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504))
        s.mount("https://", HTTPAdapter(max_retries=retry))
        s.mount("http://", HTTPAdapter(max_retries=retry))
        s.headers.update({
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
        })
        _session = s
    return _session


def _fetch_intermediates(host: str, port: int = 443) -> str:
    """Download the issuer certificate(s) named in the server cert's AIA field."""
    from cryptography import x509
    from cryptography.hazmat.primitives.serialization import Encoding
    from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # only to *read* the leaf cert; real request is verified
    with socket.create_connection((host, port), timeout=20) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)

    pems: list[str] = []
    cert = x509.load_der_x509_certificate(der)
    for _ in range(3):  # walk up to 3 levels
        try:
            aia = cert.extensions.get_extension_for_oid(ExtensionOID.AUTHORITY_INFORMATION_ACCESS).value
        except x509.ExtensionNotFound:
            break
        urls = [d.access_location.value for d in aia
                if d.access_method == AuthorityInformationAccessOID.CA_ISSUERS]
        if not urls:
            break
        data = requests.get(urls[0], timeout=20, headers={"User-Agent": UA}).content
        try:
            issuer = x509.load_der_x509_certificate(data)
        except ValueError:
            issuer = x509.load_pem_x509_certificate(data)
        pems.append(issuer.public_bytes(Encoding.PEM).decode())
        if issuer.issuer == issuer.subject:
            break
        cert = issuer
    return "".join(pems)


def _bundle_with(pem: str) -> str:
    with open(certifi.where(), encoding="utf-8") as f:
        base = f.read()
    fd, path = tempfile.mkstemp(suffix=".pem")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(base + "\n" + pem)
    return path


def fetch_html(url: str) -> str:
    host = urlparse(url).hostname or ""
    verify: str | bool = _bundle_with(_extra_pems[host]) if host in _extra_pems else True
    try:
        r = session().get(url, timeout=TIMEOUT, verify=verify)
    except requests.exceptions.SSLError:
        pem = _fetch_intermediates(host)
        if not pem:
            raise
        _extra_pems[host] = pem
        r = session().get(url, timeout=TIMEOUT, verify=_bundle_with(pem))
    r.raise_for_status()
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    return r.text


_browser = None
_pw = None


def fetch_rendered(url: str) -> str:
    """Open the page in headless Chromium (for JavaScript-built sites)."""
    global _browser, _pw
    if _browser is None:
        from playwright.sync_api import sync_playwright
        _pw = sync_playwright().start()
        _browser = _pw.chromium.launch()
    page = _browser.new_page(user_agent=UA, ignore_https_errors=False)
    try:
        page.goto(url, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(2500)
        return page.content()
    finally:
        page.close()


def close():
    global _browser, _pw
    if _browser is not None:
        _browser.close()
        _pw.stop()
        _browser = _pw = None
