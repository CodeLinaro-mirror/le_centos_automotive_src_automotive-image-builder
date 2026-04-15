import os
import re
import sys

__version__ = "1.3.0"


def get_version():
    return __version__


def bump_patch():
    major, minor, patch = __version__.split(".")
    new_version = f"{major}.{minor}.{int(patch) + 1}"

    version_file = os.path.abspath(__file__)
    with open(version_file, "r") as f:
        content = f.read()

    content = re.sub(
        r'^__version__ = ".*"',
        f'__version__ = "{new_version}"',
        content,
        count=1,
        flags=re.MULTILINE,
    )

    with open(version_file, "w") as f:
        f.write(content)

    return new_version


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "bump":
        print(bump_patch())
    else:
        print(__version__)
