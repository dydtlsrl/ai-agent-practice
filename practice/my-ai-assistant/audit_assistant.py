"""audit_assistant.py - 읽기 전용 점검 스크립트 (키 값은 절대 출력하지 않음)"""
import importlib.metadata as md
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
counts = {"OK": 0, "INFO": 0, "WARN": 0, "FAIL": 0}


def report(level, msg):
    counts[level] += 1
    print(f"  [{level}] {msg}")


def git(*args):
    try:
        p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=20)
        return p.returncode, p.stdout
    except Exception:
        return 1, ""


def candidate_files():
    """커밋될 수 있는 파일 목록(.gitignore 대상인 .env, .venv 제외)"""
    code, out = git("ls-files", "-co", "--exclude-standard")
    if code == 0 and out.strip():
        return [ROOT / p for p in out.splitlines() if (ROOT / p).is_file()]
    return [p for p in ROOT.rglob("*")
            if p.is_file() and ".venv" not in p.parts and ".git" not in p.parts]


def read_text(path):
    try:
        if path.stat().st_size > 1_000_000:
            return None
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def parse_env(path):
    data = {}
    text = read_text(path) if path.is_file() else None
    for line in (text or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def value_status(v):
    if not v:
        return "비어 있음"
    if "your" in v.lower():
        return "예시 값"
    return "설정됨"


files = candidate_files()
py_files = [f for f in files if f.suffix == ".py"]

print("== 1. 실행 환경 ==")
in_venv = sys.prefix != sys.base_prefix
report("OK" if in_venv else "WARN", f"가상환경 {'활성' if in_venv else '비활성'}")
ver = sys.version.split()[0]
report("OK" if ver.startswith("3.12") else "WARN", f"Python {ver} (과정 권장: 3.12)")

print("\n== 2. 환경변수 이름 일치 ==")
env = parse_env(ROOT / ".env")
example = parse_env(ROOT / ".env.example")
if not env:
    report("FAIL", ".env가 없거나 비어 있음")
for k, v in env.items():
    report("INFO", f".env {k}: {value_status(v)}")

code_names = set()
for f in py_files:
    if "tests" in f.parts:
        continue
    text = read_text(f) or ""
    code_names |= set(re.findall(r'["\']((?:OPENAI|GEMINI|MAX)_[A-Z0-9_]+)["\']', text))
for n in sorted(code_names - set(env)):
    report("WARN", f"코드가 읽는 {n}이(가) .env에 없음")
for n in sorted(set(env) - code_names):
    report("INFO", f".env의 {n}은(는) 코드(tests 제외)에서 참조되지 않음 (이름 불일치 가능성)")
for n in sorted(set(env) - set(example)):
    report("INFO", f"{n}이(가) .env.example에 없음")

print("\n== 3. 키 유출 위험 ==")
rc, _ = git("check-ignore", "-q", ".env")
report("OK" if rc == 0 else "FAIL", ".env는 Git에서 제외됨" if rc == 0 else ".env가 Git 제외 대상이 아님!")
pattern = re.compile(r"AIza[0-9A-Za-z_\-]{20,}|sk-[A-Za-z0-9_\-]{20,}")
leaked = False
for f in files:
    text = read_text(f)
    if text is None:
        continue
    for i, line in enumerate(text.splitlines(), 1):
        if pattern.search(line):
            leaked = True
            report("FAIL", f"키 형태 발견: {f.relative_to(ROOT)}:{i} (값은 출력하지 않음)")
if not leaked:
    report("OK", "커밋 가능한 파일에서 키 형태 문자열 없음")

print("\n== 4. 하드코딩 ==")
found = False
for f in py_files:
    if "tests" in f.parts or f.name == Path(__file__).name:
        continue
    for i, line in enumerate((read_text(f) or "").splitlines(), 1):
        if re.search(r"max_(?:output_|completion_)?tokens\s*=\s*\d+", line) or \
           re.search(r'["\'](?:gpt-|gemini-|text-embedding-)[\w.\-]*["\']', line):
            found = True
            report("WARN", f"{f.name}:{i}: {line.strip()[:90]}")
if not found:
    report("OK", "하드코딩된 출력 토큰 상한/모델 이름 없음")

print("\n== 5. 패키지 ==")
for pkg, must in [("openai", True), ("google-genai", True), ("python-dotenv", False),
                  ("chromadb", False), ("fastapi", False)]:
    try:
        report("OK", f"{pkg} {md.version(pkg)}")
    except md.PackageNotFoundError:
        report("WARN" if must else "INFO", f"{pkg} 미설치")

print("\n== 6. 필수 파일 ==")
for name in ["main.py", "requirements.txt", ".env.example", "tests"]:
    report("OK" if (ROOT / name).exists() else "FAIL", f"{name} {'있음' if (ROOT / name).exists() else '없음'}")

if "--tests" in sys.argv:
    print("\n== 7. 자동 테스트 ==")
    p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                       cwd=ROOT, capture_output=True, text=True)
    tail = (p.stderr or p.stdout).strip().splitlines()[-4:]
    report("OK" if p.returncode == 0 else "FAIL", "테스트 통과" if p.returncode == 0 else "테스트 실패")
    for line in tail:
        print("     ", line)

print(f"\n요약: {counts}")