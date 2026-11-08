# opds-mirror

Mirror every book from one or more OPDS catalogs (Calibre content server,
Calibre-Web, or any OPDS 1.x catalog) into a folder tree:

```
<output_dir>/<Author>/<Title>/<Title>.<ext>
```

Every format a server offers is downloaded (EPUB, PDF, MOBI, AZW3, ...).
Re-running only downloads files that aren't there yet.

> Status: step 1 of 3. Crawling and downloading work. Duplicate detection by
> hash, ISBN and author+title against an existing library, and cron hardening
> (lock file, log file), are coming next.

## Install

Needs Python 3.11 or newer.

```sh
git clone https://github.com/talonius/opds-mirror
cd opds-mirror
python -m venv .venv
.venv/bin/pip install .
```

## Configure

Copy `config.example.toml` to `config.toml` and edit it. List one `[[servers]]`
block per server. Both Calibre and Calibre-Web serve their catalog at `/opds`:

```toml
output_dir = "~/Books/opds-mirror"

[[servers]]
name = "calibre"
url = "http://calibre.local:8080/opds"

[[servers]]
name = "calibre-web"
url = "http://calibre-web.local:8083/opds"
```

A Calibre content server with several libraries needs one block per library,
with `?library_id=<library name>` on the end of the URL.

## Run

```sh
.venv/bin/opds-mirror -c config.toml sync --dry-run   # show what would download
.venv/bin/opds-mirror -c config.toml sync             # download
```

`-v` logs every request, `-q` logs only warnings and errors. The exit code is 0
when everything worked and 1 if any file or server failed.

## How it works

The crawler starts at each server's root feed and follows every navigation link
and "next page" link on the same host, visiting each page once. Every book entry
is recognised by its Atom id, so a book listed under "By Newest", "By Author"
and "By Tag" is only processed once. Downloads go to
`<output_dir>/.opds-mirror/tmp/` first and are moved into place only once
complete, so an interrupted run never leaves half a book behind.

## Development

```sh
pip install -e '.[dev]'
pytest
```
