"""Host Replace Nox configuration"""
import shutil
import nox

@nox.session
def lint_nox(session):
    """Lint the noxfile."""
    session.install("pylint", "nox")
    session.run("pylint", "noxfile.py")

@nox.session
def lint_module(session):
    """Lint the module code."""
    session.install("pylint")
    session.install("-r", "requirements.txt")
    session.run("pylint", *session.posargs, "src")

@nox.session
def lint_tests(session):
    """Lint the unit tests."""
    session.install("pylint")
    session.install(".")
    session.run("pylint", *session.posargs, "tests")

@nox.session
def trailing_whitespace(session):
    """Check for trailing whitespace in tracked files."""
    result = session.run("git", "ls-files", silent=True, external=True)
    files = result.strip().splitlines()

    result = session.run(
        "grep", "-nE", r"\s$", *files, success_codes=[1], silent=True, external=True
    )

    if result:
        session.error("Trailing whitespace found:\n" + result)

@nox.session
def mypy(session):
    """Run type checks using mypy."""
    session.install("mypy", "types-regex")
    session.install("-r", "requirements.txt")
    session.run("mypy", *session.posargs)

@nox.session(python=["3.9", "3.10", "3.11"])
def tests(session):
    """Run the unit tests."""
    session.install("pytest")
    session.install(".")
    session.run("pytest", *session.posargs, "tests")

@nox.session
def build_and_check_dists(session):
    """Build and check distributions with build, check-manifest, and twine."""
    session.install("build", "check-manifest >= 0.42", "twine")
    shutil.rmtree("dist", ignore_errors=True)
    shutil.rmtree("build", ignore_errors=True)
    session.run("python", "-m", "build")
    session.run("check-manifest")
    session.run("python", "-m", "twine", "check", "dist/*")
