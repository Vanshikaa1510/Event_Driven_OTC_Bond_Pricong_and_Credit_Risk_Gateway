package com.otc.rfq.api;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;

public record DashboardSummary(
        String clientId,
        BigDecimal creditLimit,
        BigDecimal currentExposure,
        BigDecimal activeReservations,
        BigDecimal availableCredit,
        Instant creditUpdatedAt,
        Instant asOf,
        List<InventorySnapshot> inventory) {

    public record InventorySnapshot(
            String isin,
            String issuer,
            int maturityYear,
            BigDecimal availableNotional,
            BigDecimal hedgeCapacity,
            BigDecimal activeReservations,
            BigDecimal remainingCapacity,
            BigDecimal marketMidYield,
            Instant updatedAt,
            boolean fresh) {}
}
