# Publishing to PyPI

Everything here is ready to upload. The name `lythosle` was free on PyPI when
these files were prepared, and both distributions pass `twine check`.

## What is in the box

| File | Purpose |
|---|---|
| `pyproject.toml` | package metadata (PEP 621 + PEP 639 licence) |
| `MANIFEST.in` | what goes into the source distribution |
| `LICENSE` | MIT, shipped inside both distributions |
| `README.md` | becomes the long description on the project page |
| `dist/lythosle-0.1.0-py3-none-any.whl` | the wheel, ready to upload |
| `dist/lythosle-0.1.0.tar.gz` | the source distribution, ready to upload |

The wheel was installed into a clean virtual environment and checked outside
the source tree: the `lythosle` command runs, the browser front end's static
files and all 14 bundled fonts are present, and the API answers.

## One-time setup

1. Create an account at <https://pypi.org/account/register/> and turn on
   two-factor authentication (PyPI requires it for uploads).
2. Create an API token at <https://pypi.org/manage/account/token/>. For the
   very first upload the token has to be account-scoped; afterwards you can
   replace it with one scoped to the `lythosle` project.
3. Put the token where twine can find it, in `~/.pypirc`:

```ini
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-AgEIcHlwaS5vcmc...      # the whole token, including "pypi-"

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-AgENdGVzdC5weXBpLm9yZw...
```

   `chmod 600 ~/.pypirc`. Alternatively export `TWINE_USERNAME=__token__` and
   `TWINE_PASSWORD=<token>` instead of keeping the file.

## Upload

```bash
python -m pip install --upgrade build twine

rm -rf dist build *.egg-info
python -m build                 # writes dist/*.whl and dist/*.tar.gz
python -m twine check dist/*    # metadata and README must both pass

# optional dry run on the test index
python -m twine upload -r testpypi dist/*
python -m pip install -i https://test.pypi.org/simple/ lythosle

# the real thing
python -m twine upload dist/*
```

The project then appears at <https://pypi.org/project/lythosle/> and anyone can

```bash
pip install lythosle
lythosle serve --open
```

If you would rather upload what was already built here, skip `python -m build`
and run `twine upload dist/*` against the two files in `dist/`.

## Releasing again later

PyPI will not accept the same version twice, not even after a delete. For each
release:

1. bump `version` in `pyproject.toml` (and `__version__` in
   `lythosle/__init__.py` — keep the two in step);
2. `rm -rf dist build *.egg-info && python -m build`;
3. `python -m twine check dist/*`;
4. `python -m twine upload dist/*`.

Use TestPyPI while experimenting: its version numbers are separate from the
real index, so a mistake there costs nothing.

## Optional: let GitHub do it

With PyPI's trusted publishing there is no token to store. Add the publisher at
<https://pypi.org/manage/account/publishing/> (owner `hdaltuntas`, repository
`lythosle`, workflow `publish.yml`, environment `pypi`), then commit:

```yaml
# .github/workflows/publish.yml
name: publish
on:
  release:
    types: [published]

jobs:
  pypi:
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write            # trusted publishing needs this
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install build
      - run: python -m build
      - uses: pypa/gh-action-pypi-publish@release/v1
```

Cutting a GitHub release then uploads the distributions by itself.

## Notes on the metadata

* The licence uses the current PEP 639 form (`license = "MIT"` plus
  `license-files`), which needs `setuptools>=77` — that is pinned in
  `[build-system]`. The old `License :: OSI Approved :: MIT License`
  classifier must stay out: setuptools rejects the combination.
* `authors` carries the name only. Add `email = "..."` if you want a contact
  address on the public project page.
* The static front end, including the bundled fonts, ships through
  `[tool.setuptools.package-data]`; `MANIFEST.in` adds the tests and docs to
  the source distribution.
