"""Hard boundary between the portfolio demonstration and other installations."""
from urllib.parse import urlparse


def assert_demo_database_target(value: str) -> None:
    target = urlparse(value)
    if (
        target.scheme not in {"postgres", "postgresql"}
        or target.hostname not in {"127.0.0.1", "localhost"}
        or target.port != 55439
        or not target.path.startswith("/oa_demo_")
    ):
        raise RuntimeError("Demonstracao isolada: use somente oa_demo_* em 127.0.0.1:55439.")
