# libre-cgm-agent

FreeStyle Libre(리브레 2·3) 연속혈당측정기 데이터를 AI 에이전트에 붙인다.
혈당을 5분마다 자동으로 모으고, 에이전트가 요약·식후 반응을 해석하고 식단 관리를 돕는다.

## 제일 쉬운 사용법

자기 에이전트(Claude Code 등)에 이렇게 말한다.

> 이 레포로 내 리브레 혈당 연결해 줘: https://github.com/hislegend/libre-cgm-agent

에이전트가 `skills/libre-cgm/SKILL.md` 를 읽고 순서대로 설치한다.
사람이 할 일은 폰에서 3단계뿐이다(보호자 앱 가입 → 리브레 앱에서 초대 → 수락).

Claude Code 스킬로 두려면 `skills/libre-cgm` 폴더를 `~/.claude/skills/` 에 복사하거나 링크한다.

## 어떻게 동작하나

```
센서 ─블루투스→ 폰 리브레 앱 ─업로드→ 애보트 서버
                                         │  (LibreLinkUp 보호자 계정으로 읽기)
                                         ▼
                          collect.py (5분마다) → SQLite
                                         ▼
                          report.py → 에이전트가 해석
```

- `libre_cgm/collect.py` — 수집 + 위험 알림(70 미만, 250 초과 30분 지속 · 텔레그램 선택)
- `libre_cgm/report.py` — 하루·기간 요약(TIR·GMI·CV), 식후 반응
- `install.sh` — 가상환경, 5분 자동 수집(macOS launchd / Linux systemd)

## 수동 설치

```bash
git clone https://github.com/hislegend/libre-cgm-agent && cd libre-cgm-agent
bash install.sh                       # ~/.config/libre-cgm/config.env 생성
# config.env 에 LLU_EMAIL 채우기, 비밀번호는 macOS 키체인 또는 LLU_PASSWORD
.venv/bin/python libre_cgm/collect.py --check
bash install.sh                       # 자동 수집 켜기
```

## 알아 둘 것

- **비공식 연결이다.** LibreLinkUp 은 애보트가 가족 공유용으로 만든 앱이다. 이 레포는 그 앱이 쓰는 서버를 [pylibrelinkup](https://github.com/robberwick/pylibrelinkup) 으로 읽는다. 애보트가 공식 지원하는 방법이 아니고, 바뀌면 끊길 수 있다.
- **의료기기가 아니다.** 해석은 참고용이다. 약 조절은 의사와 정한다. 저혈당 증상이 있으면 손끝 채혈로 확인한다.
- 혈당 데이터와 비밀번호는 자기 컴퓨터에만 남는다(`~/.local/share/libre-cgm`, 키체인/권한 600 설정 파일).

## 라이선스

MIT
