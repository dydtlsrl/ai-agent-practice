import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# .env 읽기: python-dotenv가 있으면 사용, 없으면 직접 읽는다
ENV_PATH = Path(__file__).parent / ".env"
try:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)
except ImportError:
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def get_json(url, headers):
    req = Request(url, headers=headers)
    with urlopen(req, timeout=20) as res:
        return json.loads(res.read().decode("utf-8"))


def list_openai(key):
    """OpenAI: 사용 가능한 모델 ID 목록 -> [(id, is_embedding)]"""
    data = get_json("https://api.openai.com/v1/models",
                    {"Authorization": f"Bearer {key}"})
    ids = sorted(m["id"] for m in data.get("data", []))
    return [(i, "embedding" in i.lower()) for i in ids]


def list_gemini(key):
    """Gemini: 모델 목록 -> [(id, is_embedding)] (키는 헤더로만 전달)"""
    result, token = [], None
    while True:
        url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200"
        if token:
            url += f"&pageToken={token}"
        data = get_json(url, {"x-goog-api-key": key})
        for m in data.get("models", []):
            name = m["name"].removeprefix("models/")
            methods = m.get("supportedGenerationMethods", [])
            result.append((name, any("embed" in x.lower() for x in methods)))
        token = data.get("nextPageToken")
        if not token:
            break
    return sorted(result)


def configured(prefix):
    """.env에서 prefix로 시작하고 MODEL/EMBED가 들어간 설정값(키는 제외)"""
    return {k: v for k, v in os.environ.items()
            if k.startswith(prefix) and ("MODEL" in k or "EMBED" in k)}


PROVIDERS = {
    "OpenAI": ("OPENAI_", "OPENAI_API_KEY", list_openai),
    "Gemini": ("GEMINI_", "GEMINI_API_KEY", list_gemini),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="전체 모델 목록도 출력")
    args = parser.parse_args()

    for name, (prefix, key_var, lister) in PROVIDERS.items():
        print(f"\n===== {name} =====")
        key = os.getenv(key_var, "")
        if not key or "your" in key.lower():
            print("API 키 미설정(또는 예시 값) -> 건너뜀")
            continue
        try:
            models = lister(key)
        except HTTPError as e:
            print(f"조회 실패: HTTP {e.code} {e.reason} (키/권한/한도를 확인하세요)")
            continue
        except URLError as e:
            print(f"네트워크 오류: {e.reason}")
            continue

        ids = {m for m, _ in models}
        embed_ids = [m for m, is_emb in models if is_emb]
        print(f"전체 모델 {len(ids)}개 / 임베딩 모델 {len(embed_ids)}개")

        print("\n[임베딩 모델 목록]  <- .env에 넣을 후보")
        for m in embed_ids:
            print(f"  - {m}")

        print("\n[.env 설정값 검증]")
        settings = configured(prefix)
        if not settings:
            print("  (MODEL/EMBED가 들어간 설정 없음)")
        for var, value in settings.items():
            mark = "OK " if value in ids else "없음"
            print(f"  [{mark}] {var} = {value}")

        if args.all:
            print("\n[전체 모델 목록]")
            for m in sorted(ids):
                print(f"  - {m}")


if __name__ == "__main__":
    main()