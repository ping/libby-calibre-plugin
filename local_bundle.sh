# Helper bash script to bundle a dev zip for local testing - macOS
version="$(git rev-parse HEAD)"
rm -f overdrive-libby-plugin-v*.zip
echo "$(git rev-parse HEAD)" > calibre-plugin/commit.txt
cd calibre-plugin && \
zip --quiet -r ../"overdrive-libby-plugin-v${version::7}.$(date +%H%M%S).zip" ./* && \
cd ..
