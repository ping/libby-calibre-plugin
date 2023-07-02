cd "${GITHUB_WORKSPACE}"
for f in calibre-plugin/translations/*.po
do
  echo "Building ${f%\.po} into ${f%\.po}.mo"
  msgfmt -o "${f%\.po}.mo" "${f%\.po}"
done
