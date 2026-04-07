from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_QUERY_KEYS = {"fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "ref", "ref_src"}


def canonicalize_url(url: str) -> str:
    raw = url.strip()
    if not raw:
        return ""

    parsed = urlsplit(raw)
    scheme = parsed.scheme.lower() or "https"
    host = parsed.hostname.lower() if parsed.hostname else ""
    port = parsed.port
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{host}:{port}"
    else:
        netloc = host

    path = parsed.path or "/"
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_KEYS
    ]

    if host == "en.wikipedia.org" and path.startswith("/wiki/"):
        return urlunsplit(("https", host, path, "", ""))
    if (host == "arxiv.org" or host.endswith(".arxiv.org")) and path.startswith("/abs/"):
        return urlunsplit(("https", "arxiv.org", "/" + path.strip("/"), "", ""))
    if host == "www.linkedin.com":
        normalized = "/" + path.strip("/")
        if normalized.startswith(("/in/", "/company/")) and not normalized.endswith("/"):
            normalized += "/"
        return urlunsplit(("https", "www.linkedin.com", normalized or "/", "", ""))
    if host == "www.amazon.com":
        segments = [segment for segment in path.split("/") if segment]
        if "dp" in segments:
            dp_index = segments.index("dp")
            if dp_index + 1 < len(segments):
                asin = segments[dp_index + 1]
                return urlunsplit(("https", "www.amazon.com", f"/dp/{asin}", "", ""))

    normalized_path = path if path == "/" else path.rstrip("/") or "/"
    normalized_query = urlencode(sorted(query_pairs))
    return urlunsplit((scheme, netloc, normalized_path, normalized_query, ""))
