# pip reinstallation test cases

This repo contains a `pip_reinstall_test.py` script which runs a variety of
reinstallation test cases.

## Usage

- Create a virtual environment with `rich` installed.
- In [pip_reinstall_test.py](./pip_reinstall_test.py), customize `PIP_VERSIONS_ARGS`.
- Run `python pip_reinstall_test.py` which will run all cases and produce `report.html`.

To add cases, customize the `CASES` list.

A typical test case looks like this:

```python
    Case(
        # The case identifier.
        name="local-wheelhouse-version-before-no-version-after",
        # pip arguments to pre-install a package in a new virtual environment.
        # This will install pip-test-package 0.1.1 in an empty venv.
        install_req=["pip-test-package==0.1.1"],
        # pip arguments to upgrade the package.
        reinstall_req=["pip-test-package"],
        variants=[
            # First variant will run `pip install pip-test-package` in the venv
            # where pip-test-package 0.1.1 is installed, which will not reinstall it.
            CaseVariant(
                reinstall_opts=[], 
                expect_reinstall=False,
            ),
            # Second variant will run `pip install --upgrade pip-test-package` in the venv
            # where pip-test-package 0.1.1 is installed, which will upgrade it to 0.1.2.
            CaseVariant(
                reinstall_opts=["--upgrade"],
                expect_reinstall=True,
                comment="will upgrade to 0.1.2",
            ),
        ],
    ),
```
