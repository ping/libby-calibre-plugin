# Helper bash script to start calibre debug with the latest plugin code loaded - macOS
for f in calibre-plugin/translations/*.po
do
  echo "Building ${f%\.po} into ${f%\.po}.mo"
  msgfmt -o "${f%\.po}.mo" "${f%\.po}"
done
echo "$(git rev-parse HEAD)" > calibre-plugin/commit.txt
calibre-debug -s; calibre-customize -b calibre-plugin; CALIBRE_OVERRIDE_LANG=en calibre-debug -g
