"""scripts/test_console_encoding.py — Windows 콘솔에서 안내 문구가 죽지 않는지

이 저장소의 주 플랫폼은 Windows 고(setup.ps1·PowerShell 안내), 기본 콘솔 인코딩은
cp949 다. 그런데 안내 문구에는 cp949 에 없는 글자가 섞여 있다 — em dash(—), ⚠, ₩.
그대로 print 하면 UnicodeEncodeError 로 죽는다. 실제로 이런 일이 있었다:

  · `sync_domain_list.py --check` — README 가 시키는 검증 명령이 성공 메시지에서 죽었다
  · `chrome_cdp.py` — Chrome 이 이미 떠 있을 때 나오는 안내가 ⚠ 에서 죽었다.
    즉 "무엇이 잘못됐는지 알려주는 문구" 자체가 크래시로 바뀌었다

CI 는 ubuntu(UTF-8) 라 이 계열 버그를 절대 잡지 못한다. 그래서 정적으로 고정한다:
**stdout 으로 안내를 내보내는 모듈은 인코딩 가드를 갖는다.**
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent

# preflight.py 가 쓰는 관용구. 인코딩 불가 문자를 '?' 로 바꾸고 계속 진행한다.
GUARD = 'reconfigure(errors="replace")'

_PRINT_CALL = re.compile(r"(?<![\w.])print\s*\(")


def _cp949_safe(text: str) -> bool:
    try:
        text.encode("cp949")
        return True
    except UnicodeEncodeError:
        return False


def _modules_that_print() -> list[Path]:
    """print() 로 사람에게 말을 거는 비테스트 모듈."""
    found = []
    for path in sorted(SCRIPTS.glob("*.py")):
        if path.name.startswith("test_") or path.name == "conftest.py":
            continue
        if _PRINT_CALL.search(io.open(path, encoding="utf-8").read()):
            found.append(path)
    return found


def test_some_modules_print():
    """수집 대상이 비면 이 파일 전체가 조용히 무력해진다."""
    assert _modules_that_print(), "print() 를 쓰는 모듈을 하나도 찾지 못했습니다"


@pytest.mark.parametrize("path", _modules_that_print(), ids=lambda p: p.name)
def test_printing_module_survives_cp949_console(path: Path):
    source = io.open(path, encoding="utf-8").read()
    if _cp949_safe(source):
        pytest.skip("cp949 로 인코딩 불가한 문자가 없다 — 가드가 필요 없다")
    assert GUARD in source, (
        f"{path.name} 은 cp949 에 없는 문자를 담고 있는데 인코딩 가드가 없습니다. "
        f"Windows 콘솔에서 UnicodeEncodeError 로 죽습니다. "
        f"preflight.py 상단의 `for _s in (sys.stdout, sys.stderr): _s.reconfigure(errors=\"replace\")` "
        f"를 그대로 넣으세요"
    )


@pytest.mark.parametrize("name", ["preflight.py", "bootstrap.py",
                                  "sync_domain_list.py", "sync_codex_mirror.py",
                                  "chrome_cdp.py"])
def test_known_entry_points_keep_the_guard(name):
    """한 번 고친 곳이 다시 열리지 않게 이름으로 못 박아 둔다."""
    assert GUARD in io.open(SCRIPTS / name, encoding="utf-8").read()
