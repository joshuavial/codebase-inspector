import pytest

from cbi.ids import normalise_remote, resolve_relative_url


@pytest.mark.parametrize("url", [
    "git@github.com:xenota-collective/xenon.git",
    "git@github.com:xenota-collective/xenon",
    "https://github.com/xenota-collective/xenon",
    "https://github.com/xenota-collective/xenon.git",
    "https://user:token@github.com/Xenota-Collective/Xenon.git/",
    "ssh://git@github.com:22/xenota-collective/xenon.git",
    "git://github.com/xenota-collective/xenon.git",
])
def test_ssh_and_https_forms_give_one_id(url):
    assert normalise_remote(url) == "github.com/xenota-collective/xenon"


@pytest.mark.parametrize("url", ["/tmp/x/lib.git", "../lib", "file:///tmp/x/lib.git", "~/src/lib"])
def test_local_remotes_use_dir_name(url):
    assert normalise_remote(url) == "local:lib"


def test_relative_submodule_urls_resolve_against_parent():
    assert resolve_relative_url("../lib.git", "git@github.com:acme/app.git") == "git@github.com:acme/lib.git"
    assert resolve_relative_url("../lib.git", "https://github.com/acme/app") == "https://github.com/acme/lib.git"
    assert resolve_relative_url("https://x.org/a/b", "git@github.com:acme/app.git") == "https://x.org/a/b"
