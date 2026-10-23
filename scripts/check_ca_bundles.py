"""Reject known unsafe roots in Python package CA bundles without editing them."""
import argparse
import hashlib
import importlib.util
from pathlib import Path
import re
import ssl


# https://github.com/advisories/GHSA-6q48-6c7w-9gw2
BLOCKED_ROOTS = {
    "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b":
        "emSign ECC Root CA - G3",
}
CERTIFICATE = re.compile(
    rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.DOTALL
)


def inspect_bundle(data):
    """Return blocked root names; reject empty or malformed certificate bundles."""
    blocks = CERTIFICATE.findall(data)
    if not blocks:
        raise ValueError("No PEM certificates found")
    if (len(blocks) != data.count(b"-----BEGIN CERTIFICATE-----")
            or len(blocks) != data.count(b"-----END CERTIFICATE-----")):
        raise ValueError("Incomplete PEM certificate")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cadata=b"\n".join(blocks).decode("ascii"))
    found = set()
    for block in blocks:
        der = ssl.PEM_cert_to_DER_cert(block.decode("ascii"))
        name = BLOCKED_ROOTS.get(hashlib.sha256(der).hexdigest())
        if name:
            found.add(name)
    return sorted(found)


def package_bundles():
    import certifi

    yield "certifi", Path(certifi.where())
    for package, relative in (
        ("grpc", "_cython/_credentials/roots.pem"),
        ("pip", "_vendor/certifi/cacert.pem"),
    ):
        spec = importlib.util.find_spec(package)
        if spec is not None:
            if spec.origin is None:
                raise ValueError(f"Cannot locate {package} CA bundle")
            yield package, Path(spec.origin).parent / relative


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, action="append", default=[],
                        help="also inspect a custom PEM CA bundle (repeatable)")
    args = parser.parse_args(argv)
    bundles = list(package_bundles())
    bundles.extend((f"custom bundle {index}", path)
                   for index, path in enumerate(args.bundle, 1))
    failures = 0
    for label, path in bundles:
        try:
            blocked = inspect_bundle(path.read_bytes())
        except (OSError, ValueError, UnicodeError) as exc:
            print(f"FAIL {label}: cannot read/validate CA bundle ({type(exc).__name__})")
            failures += 1
            continue
        if blocked:
            print(f"FAIL {label}: contains {', '.join(blocked)}")
            failures += 1
        else:
            print(f"OK {label}: no blocked root")
    if failures:
        return 1
    print(f"Checked {len(bundles)} package/custom bundles; system trust stores are not inspected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
