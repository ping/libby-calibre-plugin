if [[ -z "$1" ]]; then
  version='0.1.4'
else
  version="$1"
fi

package_name='libby-calibre-plugin'

# https://www.gnu.org/software/gettext/manual/gettext.html#xgettext-Invocation
xgettext -L Python \
  --package-name="$package_name" \
  --package-version="$version" \
  --msgid-bugs-address='https://github.com/ping/libby-calibre-plugin/' \
  --copyright-holder='ping <http://github.com/ping>' \
  -o calibre-plugin/translations/default.pot calibre-plugin/*.py calibre-plugin/**/*.py

# https://www.gnu.org/software/gettext/manual/gettext.html#msgmerge-Invocation
for f in calibre-plugin/translations/*.po
do
  echo "Updating ${f} from default.pot"
  msgmerge --no-fuzzy-matching --update "${f}" "calibre-plugin/translations/default.pot"
  sed -i'' -e "s/Project-Id-Version: .*\\\n/Project-Id-Version: ${package_name} ${version}\\\n/" $f
  rm -f "${f}-e"
  rm -f "${f}~"
  echo "Building ${f} into ${f%\.po}.mo"
  msgfmt -o "${f%\.po}.mo" "${f%\.po}"
done
