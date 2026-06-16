#!/bin/bash
pip install -r requirements.txt
# Download Noto Sans CJK TC font for Linux deployment
if [ ! -f NotoSansCJK.otf ]; then
  echo "Downloading Noto Sans CJK font..."
  curl -L "https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/TC/NotoSansCJKtc-Regular.otf" -o NotoSansCJK.otf
fi
