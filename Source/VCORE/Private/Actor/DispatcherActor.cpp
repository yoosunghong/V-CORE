#include "DispatcherActor.h"

#include "AGVActor.h"
#include "StationActor.h"
#include "TrafficManagerActor.h"

ADispatcherActor::ADispatcherActor()
{
    PrimaryActorTick.bCanEverTick = false;
}

void ADispatcherActor::Configure(ATrafficManagerActor* InTrafficManager)
{
    TrafficManager = InTrafficManager;
}

AAGVActor* ADispatcherActor::SelectAgvForStation(
    const TArray<TObjectPtr<AAGVActor>>& Agvs,
    AStationActor* Station,
    const FString& RequestedAgvId,
    FDispatchScoreBreakdown& OutBestScore) const
{
    AAGVActor* BestAgv = nullptr;
    OutBestScore = FDispatchScoreBreakdown{};

    for (AAGVActor* Agv : Agvs)
    {
        FDispatchScoreBreakdown Score = ScoreAgvForStation(Agv, Station, RequestedAgvId);
        if (!Score.bEligible)
        {
            continue;
        }

        if (!BestAgv || Score.TotalScore > OutBestScore.TotalScore)
        {
            BestAgv = Agv;
            OutBestScore = Score;
        }
    }

    return BestAgv;
}

AStationActor* ADispatcherActor::SelectStationForAgv(
    AAGVActor* Agv,
    const TArray<AStationActor*>& CandidateStations,
    FDispatchScoreBreakdown& OutBestScore) const
{
    AStationActor* BestStation = nullptr;
    OutBestScore = FDispatchScoreBreakdown{};

    if (!IsValid(Agv))
    {
        return nullptr;
    }

    for (AStationActor* Station : CandidateStations)
    {
        // Score this specific AGV against the candidate (RequestedAgvId pins it to this AGV).
        FDispatchScoreBreakdown Score = ScoreAgvForStation(Agv, Station, Agv->GetAgvId());
        if (!Score.bEligible)
        {
            continue;
        }

        if (!BestStation || Score.TotalScore > OutBestScore.TotalScore)
        {
            BestStation = Station;
            OutBestScore = Score;
        }
    }

    return BestStation;
}

FDispatchScoreBreakdown ADispatcherActor::ScoreAgvForStation(AAGVActor* Agv, AStationActor* Station, const FString& RequestedAgvId) const
{
    FDispatchScoreBreakdown Score;
    Score.RouteSegmentId = TrafficManager ? TrafficManager->GetDefaultIntersectionSegmentId() : TEXT("INTERSECTION_X");

    if (!IsValid(Agv))
    {
        Score.Explanation = TEXT("invalid_agv");
        return Score;
    }

    Score.AgvId = Agv->GetAgvId();
    if (!RequestedAgvId.IsEmpty() && !Agv->GetAgvId().Equals(RequestedAgvId, ESearchCase::IgnoreCase))
    {
        Score.Explanation = TEXT("requested_agv_mismatch");
        return Score;
    }

    if (!IsValid(Station))
    {
        Score.Explanation = TEXT("missing_station");
        return Score;
    }

    const bool bStopped = Agv->GetStateName() == TEXT("STOPPED_COLLISION");
    // Station metadata now gates/colours eligibility (P6.1c): a station with no capacity is not a
    // valid target; capability breadth and a configured zone are tie-breaking fit signals.
    const bool bHasCapacity = Station->Capacity > 0;
    const bool bStationReady = Station->bReady && Station->bAccessible;
    const bool bStationReservable = Station->GetReservedByAgvId().IsEmpty() || Station->GetReservedByAgvId() == Agv->GetAgvId();
    const bool bStationUsable = bStationReady && bStationReservable && bHasCapacity;
    const bool bRouteAvailable = !TrafficManager || TrafficManager->CanReserveSegmentFor(Agv, Score.RouteSegmentId);

    const float CapacityScore = FMath::Clamp(static_cast<float>(Station->Capacity), 0.0f, 4.0f) * 5.0f;        // 0..20
    const float CapabilityScore = FMath::Clamp(static_cast<float>(Station->CapabilityTags.Num()), 0.0f, 5.0f) * 2.0f; // 0..10
    const float ZoneScore = Station->ZoneId.IsEmpty() ? 0.0f : 5.0f;

    Score.bEligible = !bStopped && bStationUsable;
    Score.AvailabilityScore = Agv->IsAvailableForDispatch() ? 45.0f : 10.0f;
    Score.AssignmentScore = Agv->HasActiveAssignment() ? -25.0f : 15.0f;
    Score.BatteryScore = FMath::Clamp(Agv->GetBatteryPercent(), 0.0f, 100.0f) * 0.2f;
    Score.EtaSeconds = Agv->EstimateEtaToStation(Station);
    Score.DistanceScore = FMath::Clamp(40.0f - Score.EtaSeconds, 0.0f, 40.0f);
    Score.StationScore = bStationUsable ? (20.0f + CapacityScore + CapabilityScore + ZoneScore) : -100.0f;
    Score.RouteScore = bRouteAvailable ? 20.0f : -15.0f;
    Score.TotalScore = Score.AvailabilityScore
        + Score.DistanceScore
        + Score.BatteryScore
        + Score.AssignmentScore
        + Score.StationScore
        + Score.RouteScore;

    Score.Explanation = FString::Printf(
        TEXT("availability=%.1f distance_eta=%.1fs distance=%.1f battery=%.1f assignment=%.1f station=%.1f(cap=%d/%.1f capability=%d/%.1f zone=%s/%.1f) route=%s/%.1f total=%.1f"),
        Score.AvailabilityScore,
        Score.EtaSeconds,
        Score.DistanceScore,
        Score.BatteryScore,
        Score.AssignmentScore,
        Score.StationScore,
        Station->Capacity, CapacityScore,
        Station->CapabilityTags.Num(), CapabilityScore,
        Station->ZoneId.IsEmpty() ? TEXT("none") : *Station->ZoneId, ZoneScore,
        bRouteAvailable ? TEXT("available") : TEXT("blocked"),
        Score.RouteScore,
        Score.TotalScore);

    return Score;
}
