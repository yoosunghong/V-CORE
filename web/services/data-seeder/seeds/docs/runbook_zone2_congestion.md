---
category: playbook
language: ko
source: ops_runbook
tags: bottleneck, zone, throughput
zone_id: 2
---

# Zone 2 혼잡 대응 런북

Zone 2는 Pickup과 Dropoff 스테이션이 인접해 경로가 겹치는 구역으로, 셀 전체에서 병목률이
가장 먼저 상승하는 지점이다. 이 런북은 Zone 2 병목이 감지되었을 때의 단계별 대응을 정의한다.

## 1. 증상 확인

혼잡 히트맵에서 Zone 2의 핫셀 비율이 상승하고, 해당 구역을 지나는 AGV의 평균 대기(avg_wait)가
늘어난다. 라이브 상태 조회로 Zone 2에 동시 진입한 AGV 수와 각 AGV의 상태(MovingToPickup /
MovingToDropoff)를 먼저 파악한다. 처리량(throughput)이 정체되거나 하락하면 병목이 처리량을
제약하기 시작한 신호다.

## 2. 1차 조치 — 동시 진입 제한

Zone 2 교차로의 예약(reservation) 우선순위를 점검하고, 동시 진입 AGV 수를 줄인다. 디스패처가
Capacity와 CapabilityTags 적합도로 배정을 분산하도록 두면 한 스테이션에 작업이 몰리는 현상이
완화된다. 이 단계에서 충돌 위험(collision_risk)이 함께 내려가는지 확인한다.

## 3. 2차 조치 — 대수 조정

1차 조치 후에도 병목률이 목표를 초과하면 가동 AGV 대수를 한 대 줄여 재가동한다. 병목률은 AGV
대수에 단조 증가하므로, 목표 병목률을 만족하는 가장 큰 대수가 최적값이다. 최적 대수 탐색은
대수를 높은 값에서 낮은 값으로 내리며 목표를 처음 만족하는 지점에서 멈춘다.

## 4. 검증

조정 후 런을 다시 수행하고, 직전 런과 비교한다. throughput·uptime은 높을수록, avg_wait·
collision_risk·bottleneck_rate는 낮을수록 개선이다. 수용 기준(acceptance)을 설정했다면 그
판정을 우선해 채택 여부를 결정한다.
