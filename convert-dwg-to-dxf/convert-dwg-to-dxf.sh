docker run --rm --platform linux/amd64 \
  -v "$(pwd)/../arch-docs/dwg:/input" \
  -v "$(pwd)/../arch-docs/dxf/:/output" \
  oda-converter \
  bash -c "xvfb-run -a ODAFileConverter /input /output ACAD2018 DXF 0 1 > /output/log.txt 2>&1; echo EXIT_CODE:\$?"
