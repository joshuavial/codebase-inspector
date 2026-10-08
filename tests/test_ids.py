import pytest

from cbi.ids import normalise_remote, repo_name, resolve_relative_url


@pytest.mark.parametrize("url", [
    "git@github.com:example/sample-lib.git",
    "git@github.com:example/sample-lib",
    "https://github.com/example/sample-lib",
    "https://github.com/example/sample-lib.git",
    "https://user:token@github.com/Example/Sample-Lib.git/",
    "ssh://git@github.com:22/example/sample-lib.git",
    "git://github.com/example/sample-lib.git",
])
def test_ssh_and_https_forms_give_one_id(url):
    assert normalise_remote(url) == "github.com/example/sample-lib"


@pytest.mark.parametrize("url", ["/tmp/x/lib.git", "../lib", "file:///tmp/x/lib.git", "~/src/lib"])
def test_local_remotes_use_dir_name(url):
    assert normalise_remote(url) == "local:lib"


@pytest.mark.parametrize("url, name", [
    ("git@github.com:Acme/SampleDesktop.git", "SampleDesktop"),
    ("https://github.com/acme/sample-desktop.git", "sample-desktop"),
    ("https://user:token@github.com/Example/Sample-Lib.git/", "Sample-Lib"),
    ("ssh://git@github.com:22/example/sample-lib.git", "sample-lib"),
    ("file:///tmp/x/Lib.git", "Lib"),
    ("/tmp/x/Lib.git", "Lib"),
    ("", None),
    (None, None),
    ("   ", None),
])
def test_repo_name_keeps_the_remote_case(url, name):
    assert repo_name(url) == name


def test_relative_submodule_urls_resolve_against_parent():
    assert resolve_relative_url("../lib.git", "git@github.com:acme/app.git") == "git@github.com:acme/lib.git"
    assert resolve_relative_url("../lib.git", "https://github.com/acme/app") == "https://github.com/acme/lib.git"
    assert resolve_relative_url("https://x.org/a/b", "git@github.com:acme/app.git") == "https://x.org/a/b"
