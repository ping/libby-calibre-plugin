# Replaces old version number for the new one
import argparse
import re
from pathlib import Path

version_sub_re = re.compile(r"__version__ = \(\d+, \d+, \d+\)")
version_re = re.compile(r"\d+\.\d+\.\d+")


def version_num(value: str):
    if not version_re.match(value):
        raise argparse.ArgumentTypeError(
            f'"{value}" is an invalid version number format'
        )
    return value


def run(src_file: str, new_version: str):
    temp_path = Path(f"{src_file}.temp")
    src_path = Path(src_file)
    with src_path.open("r", encoding="utf-8") as f_in, temp_path.open(
        "w", encoding="utf-8"
    ) as f_out:
        while True:
            line = f_in.readline()
            if not line:
                break
            mobj = version_sub_re.search(line)
            if not mobj:
                f_out.write(line)
                continue
            version_tuple = new_version.split(".")
            new_line = version_sub_re.sub(
                f'__version__ = ({", ".join(version_tuple)})',
                line,
            )
            print(
                f"{src_file}:\n"
                f"* before:\t{line.strip()}"
                f"\n* after:\t{new_line.strip()}"
            )
            f_out.write(new_line)
    temp_path.rename(src_file)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bump version")
    parser.add_argument(
        "new_version", type=version_num, help="New version number. Format d.d.d"
    )

    args = parser.parse_args()
    src_files = ("calibre-plugin/__init__.py",)
    for src in src_files:
        run(src, args.new_version)

    print(f'\nROLLBACK git commands:\ngit restore {" ".join(src_files)}\n')

    print(
        f'COMMIT git commands:\ngit add -u {" ".join(src_files)} calibre-plugin/translations/ translate.sh'
    )
    print(f"git commit -m 'Bump version to {args.new_version}'")
    print(f"git tag --sign -a 'v{args.new_version}' -m 'Release v{args.new_version}'")
    print("git push && git push --tags\n")
