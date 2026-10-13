set -u
for R in /home/kesha/orchestra /home/kesha/projects/seedon; do
  n=$(basename $R); echo "=== $n tracked at HEAD"; 
  git -C $R ls-tree -r -l HEAD | awk '{s+=$4;c++}END{printf "files=%d bytes=%.2f GB\n",c,s/1e9}'
  git -C $R ls-tree -r -l HEAD | awk '{split($5,a,"/"); k=(a[1]==".orchestra"&&a[2]=="tasks")?".orchestra/tasks":a[1]; s[k]+=$4}END{for(k in s)printf "%.3f GB\t%s\n",s[k]/1e9,k}' | sort -rn | head -6
  D=/tmp/v836-$n;  
  /usr/bin/time -f "clone --no-checkout -s: %e s" git clone -q -s --no-checkout $R $D
  cd $D
  /usr/bin/time -f "full checkout: %e s" git checkout -q HEAD 2>&1
  echo "disk full: $(du -sxB1 $D --exclude=.git | cut -f1 | awk '{printf "%.3f GB",$1/1e9}')"; ls | head -0
  cd /; 
  D2=/tmp/v836-$n-sparse; 
  git clone -q -s --no-checkout $R $D2; cd $D2
  git sparse-checkout init --cone >/dev/null 2>&1
  TOP=$(git ls-tree --name-only HEAD | grep -v -E '^(artifacts|\.orchestra)$' | tr '\n' ' ')
  dirs=$(git ls-tree -d --name-only HEAD | grep -v -E '^(artifacts|\.orchestra)$' | tr '\n' ' ')
  git sparse-checkout set $dirs >/dev/null 2>&1
  /usr/bin/time -f "sparse checkout (no artifacts/.orchestra dirs): %e s" git checkout -q HEAD 2>&1
  echo "disk sparse: $(du -sxB1 $D2 --exclude=.git | cut -f1 | awk '{printf "%.3f GB",$1/1e9}')"
  cd /; trash $D $D2; trash-rm "v836-*"
done
