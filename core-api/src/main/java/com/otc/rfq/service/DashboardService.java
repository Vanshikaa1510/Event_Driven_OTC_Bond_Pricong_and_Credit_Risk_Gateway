package com.otc.rfq.service;

import com.otc.rfq.api.DashboardSummary;
import com.otc.rfq.api.DashboardSummary.InventorySnapshot;
import java.math.BigDecimal;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;

@Service
public class DashboardService {
    private static final Duration MAX_MARKET_AGE = Duration.ofHours(24);

    private final JdbcTemplate jdbcTemplate;

    public DashboardService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public List<String> listClients() {
        return jdbcTemplate.queryForList(
                "SELECT client_id FROM client_credit_limits ORDER BY client_id", String.class);
    }

    public DashboardSummary getSummary(String clientId) {
        List<CreditSnapshot> creditRows = jdbcTemplate.query(
                """
                SELECT c.credit_limit, c.current_exposure,
                       COALESCE((
                           SELECT SUM(r.amount)
                           FROM credit_reservations r
                           WHERE r.client_id = c.client_id AND r.expires_at > now()
                       ), 0) AS active_reservations,
                       c.updated_at
                FROM client_credit_limits c
                WHERE c.client_id = ?
                """,
                (rs, rowNum) -> new CreditSnapshot(
                        rs.getBigDecimal("credit_limit"),
                        rs.getBigDecimal("current_exposure"),
                        rs.getBigDecimal("active_reservations"),
                        rs.getTimestamp("updated_at").toInstant()),
                clientId);
        if (creditRows.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "No credit profile exists for this client");
        }

        CreditSnapshot credit = creditRows.getFirst();
        List<InventorySnapshot> inventory = jdbcTemplate.query(
                """
                SELECT inventory.isin, inventory.issuer, inventory.maturity_year,
                       inventory.available_notional, inventory.hedge_capacity,
                       COALESCE(reservations.active_amount, 0) AS active_reservations,
                       inventory.market_mid_yield, inventory.updated_at
                FROM bond_inventory inventory
                LEFT JOIN (
                    SELECT isin, SUM(amount) AS active_amount
                    FROM bond_inventory_reservations
                    WHERE expires_at > now()
                    GROUP BY isin
                ) reservations ON reservations.isin = inventory.isin
                ORDER BY inventory.issuer, inventory.maturity_year
                """,
                (rs, rowNum) -> {
                    Instant updatedAt = rs.getTimestamp("updated_at").toInstant();
                    BigDecimal availableNotional = rs.getBigDecimal("available_notional");
                    BigDecimal hedgeCapacity = rs.getBigDecimal("hedge_capacity");
                    BigDecimal activeReservations = rs.getBigDecimal("active_reservations");
                    return new InventorySnapshot(
                            rs.getString("isin"),
                            rs.getString("issuer"),
                            rs.getInt("maturity_year"),
                            availableNotional,
                            hedgeCapacity,
                            activeReservations,
                            availableNotional.add(hedgeCapacity).subtract(activeReservations).max(BigDecimal.ZERO),
                            rs.getBigDecimal("market_mid_yield"),
                            updatedAt,
                            Duration.between(updatedAt, Instant.now()).compareTo(MAX_MARKET_AGE) <= 0);
                });
        BigDecimal availableCredit = credit.limit()
                .subtract(credit.exposure())
                .subtract(credit.activeReservations());
        return new DashboardSummary(
                clientId,
                credit.limit(),
                credit.exposure(),
                credit.activeReservations(),
                availableCredit,
                credit.updatedAt(),
                Instant.now(),
                inventory);
    }

    private record CreditSnapshot(
            BigDecimal limit, BigDecimal exposure, BigDecimal activeReservations, Instant updatedAt) {}
}
