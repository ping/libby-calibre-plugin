if [[ -z "$1" ]]; then
  version='0.1.3'
else
  version="$1"
fi

# https://www.gnu.org/software/gettext/manual/gettext.html#xgettext-Invocation
xgettext -L Python \
  --package-name='libby-calibre-plugin' \
  --package-version="$version" \
  --msgid-bugs-address='https://github.com/ping/libby-calibre-plugin/' \
  --copyright-holder='ping <http://github.com/ping>' \
  -o calibre-plugin/translations/default.pot calibre-plugin/*.py

# https://www.gnu.org/software/gettext/manual/gettext.html#msgmerge-Invocation
for f in calibre-plugin/translations/*.po
do
  echo "Updating ${f} from default.pot"
  msgmerge --update "${f}" "calibre-plugin/translations/default.pot"
  echo "Building ${f%\.po} into ${f%\.po}.mo"
  msgfmt -o "${f%\.po}.mo" "${f%\.po}"
done
