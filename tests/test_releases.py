"""Tests for building releases.json from the ASF release catalog."""

from asfmetrics.collectors.projects_apache_org import build_releases_by_project


CATALOG = {
    "httpd-http-server": {
        "pmc": "httpd", "name": "Apache HTTP Server",
        "release": [
            {"name": "Apache HTTP Server", "revision": "2.4.69", "created": "2026-10-01"},
            {"name": "Apache HTTP Server", "revision": "2.4.68", "created": "2026-06-08"},
        ],
    },
    "httpd-mod-ftp": {
        "pmc": "httpd", "name": "Apache mod_ftp",
        "release": [{"name": "Apache mod_ftp", "revision": "0.9.6-beta", "created": "2009-10-08"}],
    },
    "incubator-seata": {
        "pmc": "incubator", "name": "Apache Seata (incubating)",
        "release": [{"revision": "2.3.0", "created": "2026-02-12"}],
    },
    "seata-go": {
        "pmc": "incubator-seata", "name": "Apache Seata Go",
        "release": [{"revision": "1.0.0", "created": "2026-03-01T00:00:00Z"}],
    },
    "broken": {"pmc": "x", "release": [{"revision": "1", "created": "not-a-date"}, "junk"]},
}


def test_groups_components_under_committee():
    out = build_releases_by_project(CATALOG, podling_ids=["seata"])
    assert out["httpd"] == {
        "HTTP Server 2.4.69": "2026-10-01",
        "HTTP Server 2.4.68": "2026-06-08",
        "mod_ftp 0.9.6-beta": "2009-10-08",
    }


def test_podlings_use_bare_podling_id():
    out = build_releases_by_project(CATALOG, podling_ids=["seata"])
    assert "incubator" not in out and "incubator-seata" not in out
    assert out["seata"]["Seata (incubating) 2.3.0"] == "2026-02-12"
    assert out["seata"]["Seata Go 1.0.0"] == "2026-03-01"   # timestamp trimmed to a date


def test_skips_bad_entries():
    out = build_releases_by_project(CATALOG, podling_ids=["seata"])
    assert "x" not in out
