#!/usr/bin/env bash
# Corpus is not committed (see .gitignore). It is rebuilt from the official
# gazette (Công báo) by scripts/prepare_corpus.py, which records every source
# URL, so the benchmark stays reproducible:
#
#   Bộ luật Lao động 2019 (45/2019/QH14)       -> data/corpus/bo_luat_lao_dong_2019.md
#   Luật Bảo hiểm xã hội 2024 (41/2024/QH15)   -> data/corpus/luat_bao_hiem_xa_hoi_2024.md
#
# Adding a document by hand instead: start it with YAML front matter (title,
# number, issued_by, effective_date, expiry_date - empty while in force), and
# keep "Điều <số>." / "<số>. " / "Chương <số La Mã>" at line starts.
set -euo pipefail
cd "$(dirname "$0")/.."
python scripts/prepare_corpus.py "$@"
