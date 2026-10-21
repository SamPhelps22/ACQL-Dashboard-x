#!/usr/bin/env sh
# Daily in season. Acts on the next unlocked week; a no-op once that week is locked.
cd "$(dirname "$0")/../.." || exit 1
python -m operation_sunday run
python -m operation_sunday check-deadline
