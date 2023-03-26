import atexit
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from dataclasses import dataclass

from rich import print
from rich.console import Console

console = Console(record=True)

HERE = Path(__file__).parent
CACHE_PATH = HERE / "cache"
WHEELHOUSE_PATH = HERE / "wheelhouse"
SRC_PATH = HERE / "src"

PIP_VERSIONS_ARGS: dict[str, tuple[str | Path, ...]] = {
    "pip 23.0.1": ("pip==23.0.1",),
    "pip #10564": ("-e", HERE / ".." / "pip"),
}

REFS_TO_CACHE = [
    "git+https://github.com/pypa/pip-test-package@7d654e66c8fa7149c165ddeffa5b56bc06619458",  # 0.1.1 on same tag
    "git+https://github.com/pypa/pip-test-package@5547fa909e83df8bd743d3978d6667497983a4b7",  # 0.1.1 on master branch
    "git+https://github.com/pypa/pip-test-package@f1c1020ebac81f9aeb5c766ff7a772f709e696ee",  # 0.1.2 on same tag
]

REFS_TO_WHEELHOUSE = [
    "git+https://github.com/pypa/pip-test-package@0.1.1",
    "git+https://github.com/pypa/pip-test-package@0.1.2",
]


@dataclass
class CaseVariant:
    reinstall_opts: list[str]
    expect_reinstall: bool
    comment: str | None = None


@dataclass
class Case:
    name: str
    install_req: list[str | Path]
    reinstall_req: list[str | Path]
    variants: list[CaseVariant]


CASES = [
    Case(
        name="vcs-different-ref-different-version",
        install_req=["git+https://github.com/pypa/pip-test-package@0.1.2"],
        reinstall_req=["git+https://github.com/pypa/pip-test-package@0.1.1"],
        variants=[
            CaseVariant(reinstall_opts=[], expect_reinstall=True),
        ],
    ),
    Case(
        name="vcs-same-ref-same-commit",
        install_req=["git+https://github.com/pypa/pip-test-package@0.1.2"],
        reinstall_req=["git+https://github.com/pypa/pip-test-package@0.1.2"],
        variants=[
            CaseVariant(reinstall_opts=[], expect_reinstall=False),
            CaseVariant(
                reinstall_opts=["--upgrade"],
                expect_reinstall=False,
                comment="should not reinstall because same immutable commit",
            ),
            CaseVariant(reinstall_opts=["--force-reinstall"], expect_reinstall=True),
        ],
    ),
    Case(
        name="vcs-different-ref-same-version-different-commit",
        install_req=["pip-test-package @ git+https://github.com/pypa/pip-test-package@0.1.1"],
        reinstall_req=["pip-test-package @ git+https://github.com/pypa/pip-test-package@5547fa909e83df8bd743d3978d6667497983a4b7"],
        variants=[
            CaseVariant(reinstall_opts=[], expect_reinstall=True),
        ],
    ),
    Case(
        name="vcs-different-ref-same-version-different-commit-no-cache",
        install_req=["--no-cache", "pip-test-package @ git+https://github.com/pypa/pip-test-package@0.1.1"],
        reinstall_req=["--no-cache", "pip-test-package @ git+https://github.com/pypa/pip-test-package@5547fa909e83df8bd743d3978d6667497983a4b7"],
        variants=[
            CaseVariant(reinstall_opts=[], expect_reinstall=True),
        ],
    ),
    Case(
        name="vcs-different-ref-same-commit",
        install_req=["pip-test-package @ git+https://github.com/pypa/pip-test-package@0.1.1"],
        reinstall_req=["pip-test-package @ git+https://github.com/pypa/pip-test-package@7d654e66c8fa7149c165ddeffa5b56bc06619458"],
        variants=[
            CaseVariant(reinstall_opts=[], expect_reinstall=False),
            CaseVariant(
                reinstall_opts=["--upgrade"],
                expect_reinstall=False,
                comment="should not reinstall because same immutable commit",
            ),
            CaseVariant(reinstall_opts=["--force-reinstall"], expect_reinstall=True),
        ],
    ),
    Case(
        name="vcs-same-commit",
        install_req=["pip-test-package @ git+https://github.com/pypa/pip-test-package@7d654e66c8fa7149c165ddeffa5b56bc06619458"],
        reinstall_req=["pip-test-package @ git+https://github.com/pypa/pip-test-package@7d654e66c8fa7149c165ddeffa5b56bc06619458"],
        variants=[
            CaseVariant(reinstall_opts=[], expect_reinstall=False),
            CaseVariant(
                reinstall_opts=["--upgrade"],
                expect_reinstall=False,
                comment="should not reinstall because same immutable commit",
            ),
            CaseVariant(reinstall_opts=["--force-reinstall"], expect_reinstall=True),
        ],
    ),
    Case(
        name="local-wheelhouse-no-version",
        install_req=["pip-test-package"],
        reinstall_req=["pip-test-package"],
        variants=[
            CaseVariant(reinstall_opts=[], expect_reinstall=False),
            CaseVariant(reinstall_opts=["--upgrade"], expect_reinstall=False),
            CaseVariant(reinstall_opts=["--force-reinstall"], expect_reinstall=True),
        ],
    ),
    Case(
        name="local-wheelhouse-version-before-no-version-after",
        install_req=["pip-test-package==0.1.1"],
        reinstall_req=["pip-test-package"],
        variants=[
            CaseVariant(reinstall_opts=[], expect_reinstall=False),
            CaseVariant(
                reinstall_opts=["--upgrade"],
                expect_reinstall=True,
                comment="will upgrade to 0.1.2",
            ),
        ],
    ),
    Case(
        name="local-wheelhouse-version-before-different-version-after",
        install_req=["pip-test-package==0.1.1"],
        reinstall_req=["pip-test-package==0.1.2"],
        variants=[CaseVariant(reinstall_opts=[], expect_reinstall=True)],
    ),
    Case(
        name="local-wheelhouse-version-before-same-version-after",
        install_req=["pip-test-package==0.1.1"],
        reinstall_req=["pip-test-package==0.1.1"],
        variants=[
            CaseVariant(reinstall_opts=[], expect_reinstall=False),
            CaseVariant(reinstall_opts=["--upgrade"], expect_reinstall=False),
            CaseVariant(reinstall_opts=["--force-reinstall"], expect_reinstall=True),
        ],
    ),
    Case(
        name="version-req-afer-vcs-ref",
        install_req=["pip-test-package @ git+https://github.com/pypa/pip-test-package@0.1.1"],
        reinstall_req=["pip-test-package==0.1.1"],
        variants=[
            CaseVariant(
                reinstall_opts=[],
                expect_reinstall=False,
                comment="same version so don't don't reinstall",
            ),
            CaseVariant(
                reinstall_opts=["--upgrade"],
                expect_reinstall=True,
                comment="same version from index instead of direct URL, should reinstall on --upgrade",
            ),
        ],
    ),
    Case(
        name="version-req-greater-ver-afer-vcs-ref",
        install_req=["pip-test-package @ git+https://github.com/pypa/pip-test-package@0.1.1"],
        reinstall_req=["pip-test-package>=0.1.1"],
        variants=[
            CaseVariant(
                reinstall_opts=[],
                expect_reinstall=False,
                comment="installed version 0.1.1 matches >= 0.1.1",
            ),
            CaseVariant(
                reinstall_opts=["--upgrade"],
                expect_reinstall=True,
                comment="upgrade to 0.1.2",
            ),
        ],
    ),
    Case(
        name="vcs-ref-afer-version-req",
        install_req=["pip-test-package==0.1.1"],
        reinstall_req=["pip-test-package @ git+https://github.com/pypa/pip-test-package@7d654e66c8fa7149c165ddeffa5b56bc06619458"],
        variants=[
            CaseVariant(
                reinstall_opts=[],
                expect_reinstall=True,
                comment="installing from direct URL for index, always reinstall",
            ),
        ],
    ),
    Case(
        name="file-wheel-same-version",
        install_req=[WHEELHOUSE_PATH / "pip_test_package-0.1.1-py3-none-any.whl"],
        reinstall_req=[WHEELHOUSE_PATH / "pip_test_package-0.1.1-py3-none-any.whl"],
        variants=[
            CaseVariant(
                reinstall_opts=[],
                expect_reinstall=False,
                comment="same direct URL, same version, don't reinstall",
            ),
            CaseVariant(
                reinstall_opts=["--upgrade"],
                expect_reinstall=True,
                comment="always reinstall file:// wheels with --upgrade",
            ),
        ],
    ),
    Case(
        name="file-sdist-same-version",
        install_req=["pip-test-package @ file:///{WHEELHOUSE_PATH}/pip-test-package-0.1.1.tar.gz"],
        reinstall_req=["pip-test-package @ file:///{WHEELHOUSE_PATH}/pip-test-package-0.1.1.tar.gz"],
        variants=[
            CaseVariant(
                reinstall_opts=[],
                expect_reinstall=False,
                comment="same direct URL, same version, don't reinstall",
            ),
            CaseVariant(
                reinstall_opts=["--upgrade"],
                expect_reinstall=True,
                comment="always reinstall remote archives with --upgrade",
            ),
        ],
    ),
    Case(
        name="remote-archive-same-url",
        install_req=["pip-test-package @ https://github.com/pypa/pip-test-package/archive/0.1.1.tar.gz"],
        reinstall_req=["pip-test-package @ https://github.com/pypa/pip-test-package/archive/0.1.1.tar.gz"],
        variants=[
            CaseVariant(
                reinstall_opts=[],
                expect_reinstall=False,
                comment="same direct URL, same version, don't reinstall",
            ),
            CaseVariant(
                reinstall_opts=["--upgrade"],
                expect_reinstall=True,
                comment="always reinstall remote archives with --upgrade",
            ),
        ],
    ),
    Case(
        name="local-editable-to-name",
        install_req=["-e", "./src/pip-test-package"],
        reinstall_req=["pip-test-package==0.1.1"],
        variants=[
            CaseVariant(
                reinstall_opts=[],
                expect_reinstall=False,
                comment="the editable install satisfies 0.1.1",
            ),
            CaseVariant(
                reinstall_opts=["--upgrade"],
                expect_reinstall=True,
                comment="from editable to index, reinstall with --upgrade",
            ),
        ],
    ),
    Case(
        name="name-to-local-editable",
        install_req=["pip-test-package==0.1.1"],
        reinstall_req=["-e", "./src/pip-test-package"],
        variants=[
            CaseVariant(
                reinstall_opts=[],
                expect_reinstall=True,
                comment="always reinstall editables",
            ),
            CaseVariant(
                reinstall_opts=["--upgrade"],
                expect_reinstall=True,
                comment="always reinstall editables",
            ),
        ],
    ),
    Case(
        name="remote-editable-to-name",
        install_req=["-e", "git+https://github.com/pypa/pip-test-package#egg=pip-test-package"],
        reinstall_req=["pip-test-package==0.1.1"],
        variants=[
            CaseVariant(
                reinstall_opts=[],
                expect_reinstall=False,
                comment="the editable install satisfies 0.1.1",
            ),
            CaseVariant(
                reinstall_opts=["--upgrade"],
                expect_reinstall=True,
                comment="from editable to index, reinstall with --upgrade",
            ),
        ],
    ),
    Case(
        name="name-to-remote-editable",
        install_req=["pip-test-package==0.1.1"],
        reinstall_req=["-e", "git+https://github.com/pypa/pip-test-package#egg=pip-test-package"],
        variants=[
            CaseVariant(
                reinstall_opts=[],
                expect_reinstall=True,
                comment="always reinstall editables",
            ),
            CaseVariant(
                reinstall_opts=["--upgrade"],
                expect_reinstall=True,
                comment="always reinstall editables",
            ),
        ],
    ),
]


def prepare() -> None:
    prepare_cache()
    prepare_wheelhouse()
    prepare_src()


def prepare_cache() -> None:
    if CACHE_PATH.is_dir():
        return
    with tempfile.TemporaryDirectory() as tmpdir:
        for ref_to_cache in REFS_TO_CACHE:
            subprocess.check_call(
                [
                    sys.executable,
                    "-m",
                    "pip" "wheel",
                    "--no-index",
                    "--cache-dir",
                    CACHE_PATH,
                    "--wheel-dir",
                    tmpdir,
                    ref_to_cache,
                ]
            )


def prepare_wheelhouse() -> None:
    if WHEELHOUSE_PATH.is_dir():
        return
    for ref_to_wheelhouse in REFS_TO_WHEELHOUSE:
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-index",
                "--no-cache",
                "--wheel-dir",
                WHEELHOUSE_PATH,
                ref_to_wheelhouse,
            ]
        )


class PipInstallResult:
    def __init__(self, result: subprocess.CompletedProcess[str]):
        self.result = result

    @property
    def uninstalled(self) -> bool:
        return "Uninstalling pip-test-package" in self.result.stdout

    @property
    def installed(self) -> bool:
        return "Successfully installed pip-test-package" in self.result.stdout

    @property
    def reinstalled(self) -> bool:
        return self.installed and self.uninstalled

    @property
    def already_satisfied(self) -> bool:
        return "Requirement already satisfied: pip-test-package" in self.result.stdout or (not self.installed and not self.reinstalled)


def prepare_src() -> None:
    if SRC_PATH.joinpath("pip-test-package").is_dir():
        return
    SRC_PATH.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        [
            "git",
            "clone",
            "--branch",
            "0.1.1",
            "https://github.com/pypa/pip-test-package",
        ],
        cwd=SRC_PATH,
    )


class VirtualEnvironment:
    def __init__(self, venv_path: Path):
        self.venv_path = venv_path

    @classmethod
    def create(cls, pip_install_args: tuple[str | Path, ...]) -> "VirtualEnvironment":
        tempdir = tempfile.TemporaryDirectory()
        venv_path = Path(tempdir.name)
        atexit.register(tempdir.cleanup)
        result = subprocess.run(
            [sys.executable, "-m", "venv", venv_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert result.returncode == 0, result.stdout
        venv = cls(venv_path)
        venv.pip_install("wheel", "coverage")
        venv.pip_install("--upgrade", *pip_install_args)
        return venv

    def pip_install(self, *args: str | Path, env: dict[str, str] = {}, coverage: bool = False) -> subprocess.CompletedProcess[str]:
        cmd: tuple[str | Path, ...] = ()
        if coverage:
            cmd = (self.venv_path / "bin" / "coverage", "run")
        else:
            cmd = (self.venv_path / "bin" / "python",)
        result = subprocess.run(
            cmd + ("-m", "pip", "install") + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        assert result.returncode == 0, result.stdout
        return result

    def pip_install_pip_test_package(self, *args: str | Path, coverage: bool = False) -> PipInstallResult:
        result = self.pip_install(
            *args,
            env={
                "PIP_CACHE_DIR": str(CACHE_PATH),
                "PIP_NO_INDEX": "1",
                "PIP_FIND_LINKS": str(WHEELHOUSE_PATH),
            },
            coverage=coverage,
        )
        return PipInstallResult(result)


class VirtualEnvironmentCache:
    _cache: dict[tuple[str | Path, ...], tuple[Path, Path]] = {}

    @classmethod
    def get(cls, pip_install_args: tuple[str | Path, ...]) -> VirtualEnvironment:
        cached = cls._cache.get(pip_install_args)
        if cached is None:
            print("Creating virtualenv for", shlex.join(str(a) for a in pip_install_args))
            venv = VirtualEnvironment.create(pip_install_args)
            tempdir = tempfile.TemporaryDirectory()
            atexit.register(tempdir.cleanup)
            venv_path_saved = Path(tempdir.name)
            shutil.copytree(venv.venv_path, venv_path_saved, dirs_exist_ok=True)
            cls._cache[pip_install_args] = venv.venv_path, venv_path_saved
            return cls.get(pip_install_args)
        else:
            venv_path, venv_path_saved = cached
            if venv_path.is_dir():
                shutil.rmtree(venv_path)
            shutil.copytree(venv_path_saved, venv_path)
            return VirtualEnvironment(venv_path)


def test_one(
    name: str,
    install_req: list[str | Path],
    reinstall_opt: list[str],
    reinstall_req: list[str | Path],
    expect_reinstall: bool,
    case_comment: str | None,
    print_output_always: bool,
) -> None:
    install_opts = install_req
    reinstall_opts = reinstall_opt + reinstall_req
    for pip_version_name, pip_version_args in PIP_VERSIONS_ARGS.items():
        venv = VirtualEnvironmentCache.get(pip_version_args)
        console.print(f"[blue bold]{name} {' '.join(str(o) for o in reinstall_opt)} - {pip_version_name}")
        if case_comment:
            console.print(f"[dim]{case_comment}[/dim]")
        console.print("│ pip install", shlex.join(str(s) for s in install_opts))
        r = venv.pip_install_pip_test_package(*install_opts)
        assert not r.already_satisfied
        assert not r.uninstalled
        assert r.installed
        console.print("│ pip install", shlex.join(str(s) for s in reinstall_opts), end="")
        r = venv.pip_install_pip_test_package(*reinstall_opts, coverage=False)
        console.print(f" > {r.already_satisfied=} {r.uninstalled=} {r.installed=}")
        success = not (r.reinstalled ^ expect_reinstall)
        if not success or print_output_always:
            console.print(
                "[dim]" + textwrap.indent(r.result.stdout, "[/dim]│[dim] ") + "[/dim]",
                end="",
            )
        if not success:
            if r.reinstalled:
                result_comment = "error: unexpected reinstall"
            else:
                result_comment = "error: did not reinstall"
        else:
            if expect_reinstall:
                result_comment = "ok: reinstalled, as expected"
            else:
                result_comment = "ok: did not reinstall, as expected"
        console.print("╰─>" + (f"[green] {result_comment}" if success else f"[red] {result_comment}"))
    console.print()


def main() -> None:
    case_names = set(sys.argv[1:])

    for case in CASES:
        if case_names and case.name not in case_names:
            continue
        for variant in case.variants:
            test_one(
                case.name,
                case.install_req,
                variant.reinstall_opts,
                case.reinstall_req,
                variant.expect_reinstall,
                variant.comment,
                print_output_always=False,
            )

    Path("report.html").write_text(console.export_html(), encoding="utf-8")

    subprocess.check_call([sys.executable, "-m", "coverage", "combine"])
    subprocess.check_call([sys.executable, "-m", "coverage", "html"])


if __name__ == "__main__":
    main()
