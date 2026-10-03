set -euxo pipefail
cd ~/.local/share/orchestra-manim
curl -sSfL --retry 5 --retry-all-errors -o /tmp/tinytex.tar.xz https://github.com/rstudio/tinytex-releases/releases/download/v2026.10/TinyTeX-1-linux-x86_64-v2026.10.tar.xz
mkdir -p tex-unpack && tar -xJf /tmp/tinytex.tar.xz -C tex-unpack && mv tex-unpack/.TinyTeX tex && rmdir tex-unpack && rm /tmp/tinytex.tar.xz
T=$PWD/tex/bin/x86_64-linux
$T/tlmgr install standalone preview dvisvgm babel-english babel-russian cyrillic lh doublestroke setspace rsfs relsize ragged2e microtype wasysym physics jknapltx wasy mathastext
$T/latex --version | head -1; $T/dvisvgm --version
du -sh tex
