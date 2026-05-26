"""알림 전송 — 디스코드 웹훅 + 카카오톡 '나에게 보내기'."""
import json
import time
import requests
import config

# ── 디스코드 ──
def send_discord(text):
    if not config.DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(config.DISCORD_WEBHOOK_URL, json={"content": text}, timeout=10)
    except Exception as e:
        print(f"[discord] 전송 실패: {e}", flush=True)

# ── 카카오 (access_token 은 refresh_token 으로 자동 갱신) ──
_kakao_token = {"access": None, "exp": 0}

def _kakao_access_token():
    now = time.time()
    if _kakao_token["access"] and now < _kakao_token["exp"] - 60:
        return _kakao_token["access"]
    if not (config.KAKAO_REST_API_KEY and config.KAKAO_REFRESH_TOKEN):
        return None
    try:
        r = requests.post(
            "https://kauth.kakao.com/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": config.KAKAO_REST_API_KEY,
                "refresh_token": config.KAKAO_REFRESH_TOKEN,
            },
            timeout=10,
        )
        d = r.json()
        _kakao_token["access"] = d.get("access_token")
        _kakao_token["exp"] = now + int(d.get("expires_in", 3600))
        return _kakao_token["access"]
    except Exception as e:
        print(f"[kakao] 토큰 갱신 실패: {e}", flush=True)
        return None

def send_kakao(text):
    token = _kakao_access_token()
    if not token:
        return
    try:
        requests.post(
            "https://kapi.kakao.com/v2/api/talk/memo/default/send",
            headers={"Authorization": f"Bearer {token}"},
            data={"template_object": json.dumps({
                "object_type": "text",
                "text": text,
                "link": {"web_url": "https://finance.naver.com"},
            }, ensure_ascii=False)},
            timeout=10,
        )
    except Exception as e:
        print(f"[kakao] 전송 실패: {e}", flush=True)

# ── ntfy.sh (전용 푸시 — PC/폰 앱에서 큰 소리·최우선 알림) ──
def send_ntfy(text, title="📈 주식 신호", priority="max"):
    if not config.NTFY_TOPIC:
        return
    try:
        requests.post(
            f"{config.NTFY_SERVER}/{config.NTFY_TOPIC}",
            data=text.encode("utf-8"),
            headers={
                "Title": title.encode("utf-8"),
                "Priority": priority,        # max=최우선(소리+방해금지 무시)
                "Tags": "rotating_light",
            },
            timeout=10,
        )
    except Exception as e:
        print(f"[ntfy] 전송 실패: {e}", flush=True)

def notify(text):
    """모든 채널 동시 전송."""
    print(f"[알림] {text}", flush=True)
    send_discord(text)
    send_kakao(text)
    send_ntfy(text)
