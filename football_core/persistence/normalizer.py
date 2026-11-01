"""Database connection URL normalization for SQLAlchemy and Neon pooling."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def normalize_database_url(url: str | None) -> str:
    """Normalize connection URL for SQLAlchemy 2.0 and Neon pooling enforcement.

    Rules:
    - Empty or None -> empty string.
    - sqlite:///... -> untouched (D-05 test compatibility).
    - postgres:// -> postgresql:// (SQLAlchemy 2.0 dialect requirement).
    - *.neon.tech -> ensures host contains '-pooler' and sslmode=require (D-04).
    """
    if not url or not url.strip():
        return ""

    raw = url.strip()

    # SQLite URLs pass through untouched
    if raw.startswith("sqlite"):
        return raw

    # Convert legacy postgres:// scheme to postgresql://
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://"):]

    parsed = urlparse(raw)
    hostname = parsed.hostname or ""

    # Neon pooling enforcement (D-04)
    if ".neon.tech" in hostname.lower():
        # Ensure -pooler is in the hostname
        if "-pooler" not in hostname:
            parts = hostname.split(".")
            # Neon endpoint ID is the first subdomain token (e.g. ep-xyz-123456)
            parts[0] = parts[0] + "-pooler"
            new_hostname = ".".join(parts)
        else:
            new_hostname = hostname

        # Reconstruct netloc with updated hostname (preserving user/password/port)
        # Using rpartition ensures any encoded characters in username/password are preserved verbatim
        userinfo, sep, host_port = parsed.netloc.rpartition("@")
        _host, sep_port, port = host_port.partition(":")
        new_host_port = f"{new_hostname}:{port}" if sep_port else new_hostname
        new_netloc = f"{userinfo}@{new_host_port}" if sep else new_host_port

        # Ensure sslmode=require in query parameters
        query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if query_params.get("sslmode") != "require":
            query_params["sslmode"] = "require"
        new_query = urlencode(query_params)

        parsed = parsed._replace(netloc=new_netloc, query=new_query)

    return urlunparse(parsed)
