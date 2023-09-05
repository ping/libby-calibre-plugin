# Helper bash script to update versions and prompt for commands to run - macOS
# Does not commit to git because we usually have to also update screenshots, readme, changelog, etc
if [[ -z "$1" ]]; then
  echo "Please specify a version number, e.g. 0.1.2"
  exit
fi

version="$1"

python3 bump_version.py "$version" && \
sed -i '' -e "s/'[0-9]*\.[0-9]*\.[0-9]*'/'${version}'/g" translate.sh && \
sh translate.sh "$version"
