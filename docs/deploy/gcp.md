# V-CORE Perforce 기반 GCP 운영 아키텍처 및 배포 자동화 계획

## 1. 프로젝트 개요

V-CORE는 UE5 기반 공정 제어 환경을 AI Agent로 제어하는 시스템이다.

사용자는 웹 인터페이스에서 자연어 명령을 입력하고, Agent는 이를 해석하여 UE5 환경의 공정 시뮬레이션, AGV 이동, 설비 제어 등을 수행한다.

Pixel Streaming은 UE5 화면을 웹에서 접근 가능하게 만드는 전달 계층으로 사용한다.

이번 개선 작업의 핵심 목표는 Pixel Streaming 자체를 깊게 최적화하는 것이 아니라, **Perforce 기반 프로젝트 구조를 유지하면서 웹/API 계층을 GCP에 분리하고, Jenkins를 통해 배포 자동화가 가능한 운영 구조를 설계하는 것**이다.

---

# 2. 핵심 설계 원칙

## 2.1 UE5 인스턴스는 로컬 GPU PC에서 실행

강화학습 목적이 아닌 한 GCP GPU 노드는 사용하지 않는다.

```text
UE5 Instance
Pixel Streaming
AI Agent Runtime
= Local GPU PC
```

## 2.2 GCP는 서비스 운영 계층으로 사용

GCP는 렌더링이 아니라 다음 역할을 담당한다.

```text
Frontend Hosting
Session API
Logging
Monitoring
Secret Management
Container Registry
```

## 2.3 Perforce를 Source of Truth로 유지

V-CORE는 Git 기반 프로젝트가 아니므로 GitHub Actions 중심 CI/CD를 사용하지 않는다.

```text
Source Control
= Perforce Helix Core
```

## 2.4 Jenkins는 향후 자동 배포 계층으로 도입

초기에는 수동 배포 스크립트로 시작하고, 이후 Jenkins가 Perforce changelist를 기준으로 빌드 및 배포를 수행한다.

```text
Perforce Submit
→ Jenkins
→ p4 sync
→ Build
→ GCP Deploy
```

## 2.5 Ray on GKE는 향후 강화학습 전용

Ray on GKE는 Pixel Streaming 운영 계층과 분리한다.

```text
Service Layer
= GCP Web/API

Training Layer
= Ray on GKE
```

---

# 3. 목표 아키텍처

```text
User Browser
    │
    ▼
GCP Frontend
Firebase Hosting
    │
    ▼
GCP Session API
Cloud Run
    │
    ▼
Signalling Server
Local or Cloud Run
    │
    ▼
Local GPU PC
    │
    ├─ UE5 Instance
    ├─ Pixel Streaming
    ├─ AI Agent Runtime
    └─ llama.cpp / Ollama / LLM Backend
```

---

# 4. Perforce 저장소 구조

예상 Depot 구조는 다음과 같이 정리한다.

```text
//UE5Depot/main/V-CORE/
    ├─ Unreal/
    │   ├─ Content/
    │   ├─ Source/
    │   ├─ Config/
    │   └─ VCORE.uproject
    │
    ├─ Web/
    │   ├─ frontend/
    │   ├─ session-api/
    │   └─ signalling/
    │
    ├─ Agent/
    │   ├─ orchestrator/
    │   ├─ tools/
    │   ├─ prompts/
    │   └─ evals/
    │
    ├─ Infra/
    │   ├─ gcp/
    │   ├─ cloud-run/
    │   ├─ firebase/
    │   ├─ jenkins/
    │   └─ scripts/
    │
    └─ Docs/
        ├─ architecture/
        ├─ deployment/
        ├─ benchmark/
        └─ portfolio/
```

---

# 5. 1차 작업: Pixel Streaming 운영 안정화

## 목표

Pixel Streaming을 깊게 최적화하지 않고, 웹 접근 가능한 안정적인 전달 계층으로 정리한다.

## 수행 범위

### 포함

* 로컬 UE5 Pixel Streaming 실행 확인
* 외부 브라우저 접속 확인
* 기본 FPS 확인
* GPU 사용률 확인
* RTT 확인
* 세션 시작 시간 확인
* Signalling Server 연결 구조 정리

### 제외

* WebRTC 내부 튜닝
* bitrate adaptive 제어
* SFU 구축
* packet loss 실험
* input-to-photon 정밀 측정
* 클라우드 게이밍 수준 최적화

## 결과물

```text
Docs/benchmark/pixel_streaming_basic_report.md
Docs/deployment/local_pixel_streaming_runbook.md
```

---

# 6. 2차 작업: 웹/API 계층 분리

## 목표

UE5 실행 환경과 웹 서비스 계층을 분리한다.

## 구성

```text
Local GPU PC
- UE5
- Pixel Streaming
- AI Agent

GCP
- Frontend
- Session API
- Logging
- Monitoring
```

## Frontend

배포 대상:

```text
Web/frontend
```

배포 위치:

```text
Firebase Hosting
```

## Session API

배포 대상:

```text
Web/session-api
```

배포 위치:

```text
Cloud Run
```

기능:

```text
GET /health
GET /sessions
POST /sessions/start
POST /sessions/end
GET /sessions/{id}
```

## 결과물

```text
Docs/architecture/service_split_architecture.md
Docs/deployment/gcp_frontend_api_deployment.md
Web/session-api/Dockerfile
Infra/gcp/deploy_session_api.sh
Infra/firebase/deploy_frontend.sh
```

---

# 7. 3차 작업: GCP 수동 배포 스크립트 구성

## 목표

Jenkins 도입 전, Perforce 기반 수동 배포 절차를 먼저 안정화한다.

## Frontend 배포 흐름

```text
p4 sync //UE5Depot/main/V-CORE/Web/frontend/...
cd Web/frontend
npm install
npm run build
firebase deploy --only hosting
```

## Session API 배포 흐름

```text
p4 sync //UE5Depot/main/V-CORE/Web/session-api/...
cd Web/session-api
gcloud builds submit \
  --tag asia-northeast3-docker.pkg.dev/PROJECT_ID/vcore/session-api:latest

gcloud run deploy vcore-session-api \
  --image asia-northeast3-docker.pkg.dev/PROJECT_ID/vcore/session-api:latest \
  --region asia-northeast3 \
  --platform managed
```

## 스크립트화

```text
Infra/scripts/deploy_frontend.sh
Infra/scripts/deploy_session_api.sh
Infra/scripts/deploy_all_web.sh
```

## 결과물

```text
Infra/scripts/
Docs/deployment/manual_deployment_runbook.md
```

---

# 8. 4차 작업: Jenkins + Perforce 기반 자동 배포 설계

## 목표

Perforce submit 이후 Jenkins가 자동으로 변경사항을 가져와 웹/API를 빌드하고 GCP에 배포하도록 구성한다.

## 자동화 흐름

```text
Developer
   │
   ▼
Perforce Submit
   │
   ▼
Jenkins Trigger
   │
   ▼
p4 sync
   │
   ▼
Change Detection
   │
   ├─ Web/frontend 변경됨
   │   └─ npm build → Firebase Hosting deploy
   │
   ├─ Web/session-api 변경됨
   │   └─ Docker build → Artifact Registry → Cloud Run deploy
   │
   └─ Docs/Agent/Unreal만 변경됨
       └─ 배포 생략 또는 문서 빌드
```

## Jenkins 역할

Jenkins는 다음만 담당한다.

```text
Perforce 변경 감지
p4 sync
frontend build
session-api build
GCP deploy
배포 로그 저장
실패 알림
```

UE5 빌드는 초기 자동화 대상에서 제외한다.

## Jenkinsfile 예시 역할

```text
Infra/jenkins/Jenkinsfile.web-deploy
```

단계:

```text
Checkout from Perforce
Detect changed paths
Build Frontend
Deploy Frontend
Build Session API
Push Image
Deploy Cloud Run
Smoke Test
```

## 결과물

```text
Infra/jenkins/Jenkinsfile.web-deploy
Docs/deployment/jenkins_perforce_gcp_cicd.md
```

---

# 9. 5차 작업: 모니터링 및 운영 안정화

## 목표

GCP에 올라간 서비스의 상태를 확인할 수 있는 운영 환경을 구성한다.

## 대상

| 항목      | 도구                     |
| ------- | ---------------------- |
| API 로그  | Cloud Logging          |
| API 상태  | Cloud Run Health Check |
| 배포 이력   | Jenkins Build History  |
| 접속 상태   | Session API            |
| Secret  | Secret Manager         |
| 기본 대시보드 | Cloud Monitoring       |

## 확인 항목

```text
Cloud Run 정상 배포 여부
Session API health check
Frontend 접속 여부
Local UE 연결 상태
Signalling 연결 상태
```

## 결과물

```text
Docs/operation/monitoring_runbook.md
Docs/operation/troubleshooting.md
```

---

# 10. 향후 확장: Ray on GKE 기반 강화학습

## 목표

향후 각 Actor 또는 AGV 단위의 강화학습을 수행할 때 Ray on GKE를 별도 학습 계층으로 도입한다.

## 원칙

Pixel Streaming 서비스 계층과 강화학습 계층은 분리한다.

```text
Service Layer
- Firebase Hosting
- Cloud Run
- Session API
- Local UE5 Pixel Streaming

Training Layer
- Ray on GKE
- RLlib
- PyTorch
- Simulation Workers
```

## 적용 후보

```text
AGV 경로 최적화
공정 병목 최소화
Actor별 정책 학습
Multi-Agent 협업
스케줄링 최적화
```

## 결과물

```text
Docs/architecture/ray_on_gke_future_training.md
```

---

# 11. 단계별 실행 순서

## Phase 1

```text
Pixel Streaming 로컬 실행 안정화
기본 측정값 기록
운영 문서 작성
```

## Phase 2

```text
Frontend / Session API 분리
GCP 수동 배포 스크립트 작성
Firebase Hosting / Cloud Run 배포
```

## Phase 3

```text
Perforce 기반 배포 절차 정리
p4 sync → build → deploy 수동 검증
```

## Phase 4

```text
Jenkins 도입
Perforce workspace 설정
Jenkinsfile 작성
자동 배포 검증
```

## Phase 5

```text
Cloud Logging / Monitoring 구성
운영 문서 정리
포트폴리오 문서화
```

## Future Phase

```text
Ray on GKE 기반 분산 강화학습 구조 설계
```

---

# 12. 최종 산출물

```text
Docs/
 ├─ architecture/
 │   ├─ service_split_architecture.md
 │   ├─ perforce_gcp_deployment_architecture.md
 │   └─ ray_on_gke_future_training.md
 │
 ├─ deployment/
 │   ├─ local_pixel_streaming_runbook.md
 │   ├─ manual_deployment_runbook.md
 │   ├─ gcp_frontend_api_deployment.md
 │   └─ jenkins_perforce_gcp_cicd.md
 │
 ├─ operation/
 │   ├─ monitoring_runbook.md
 │   └─ troubleshooting.md
 │
 └─ portfolio/
     └─ vcore_cloud_architecture_summary.md
```

---

# 13. 이 작업으로 확보하는 역량

## Perforce 기반 협업/운영 역량

* Perforce depot 구조 설계
* p4 sync 기반 빌드 절차
* changelist 기반 배포 흐름 이해
* 게임 개발 환경에 맞는 CI/CD 설계

## GCP 서비스 운영 역량

* Firebase Hosting
* Cloud Run
* Artifact Registry
* Cloud Logging
* Cloud Monitoring
* Secret Manager

## Jenkins 기반 CI/CD 역량

* Jenkins Pipeline 작성
* Perforce 연동
* 빌드/배포 자동화
* 배포 실패 대응
* 운영 로그 관리

## UE5 서비스화 역량

* UE5 Pixel Streaming 운영
* 로컬 GPU 렌더링 서버 운영
* 웹/API 계층과 UE 렌더링 계층 분리
* 실시간 3D 시스템 서비스 구조 설계

## AI Agent 시스템 운영 역량

* AI Agent를 단순 로컬 데모가 아닌 서비스 구조로 분리
* 자연어 기반 공정 제어 시스템 운영
* LLM inference backend와 웹 서비스 계층 연동

## 향후 Physical AI / RL 확장 기반

* Ray on GKE 학습 구조 설계
* Multi-Agent RL 확장 준비
* 스마트팩토리 공정 최적화 구조 이해
* 서비스 계층과 학습 계층 분리 설계

---

# 14. 포트폴리오 표현

V-CORE는 UE5 기반 공정 제어 환경을 AI Agent로 제어하는 실시간 3D 시스템이다.

Pixel Streaming을 통해 UE5 환경을 웹에서 제어 가능하게 구성하고, UE5 렌더링 인스턴스는 로컬 GPU PC에서 실행하도록 유지하였다. 대신 웹 프론트엔드와 Session API는 GCP 기반 서비스 계층으로 분리하여 운영 구조를 개선하였다.

프로젝트는 Perforce 기반으로 관리되며, 초기에는 p4 sync 기반 수동 배포 스크립트를 통해 Firebase Hosting과 Cloud Run에 배포한다. 이후 Jenkins와 Perforce를 연동하여 changelist submit 기반으로 Frontend와 Session API를 자동 빌드 및 배포하는 CI/CD 구조로 확장할 수 있도록 설계하였다.

이를 통해 단순 UE5 데모가 아니라, Perforce 기반 게임 개발 환경에서 클라우드 서비스 운영, 배포 자동화, 모니터링, AI Agent 시스템 운영까지 고려한 실시간 3D AI 서비스 아키텍처를 구축하였다.
