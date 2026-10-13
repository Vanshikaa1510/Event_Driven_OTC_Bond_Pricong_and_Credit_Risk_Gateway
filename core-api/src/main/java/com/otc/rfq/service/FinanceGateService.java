package com.otc.rfq.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.otc.rfq.domain.RfqRecord;
import com.otc.rfq.domain.RfqStatus;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

@Service
public class FinanceGateService {
    private static final Logger logger = LoggerFactory.getLogger(FinanceGateService.class);
    private static final BigDecimal ABSOLUTE_NOTIONAL_CEILING = new BigDecimal("100000000.00");
    private static final Duration MAX_MARKET_AGE = Duration.ofHours(24);
    private static final int QUOTE_RESERVATION_SECONDS = 15;

    private final JdbcTemplate jdbcTemplate;

    public FinanceGateService(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public GateResult evaluateAndReserve(RfqRecord rfq, JsonNode workerResult) {
        ObjectNode result = workerResult.deepCopy();
        List<String> violations = new ArrayList<>();
        String workerStatus = text(result, "status");
        JsonNode extracted = findAgentDetails(result, "Intent Agent").path("rfq");
        JsonNode quote = result.path("quote");

        if (!"QUOTE_PROPOSED".equals(workerStatus)) {
            if ("NEEDS_REVIEW".equals(workerStatus)) {
                JsonNode extractionErrors = findAgentDetails(result, "Intent Agent").path("errors");
                extractionErrors.forEach(error -> violations.add(error.asText()));
            } else {
                violations.add("The agent workflow did not propose a quote.");
            }
            RfqStatus status = "NEEDS_REVIEW".equals(workerStatus) ? RfqStatus.NEEDS_REVIEW : RfqStatus.REJECTED;
            return finish(result, rfq, status, violations, false, null);
        }

        if (!agentPassed(result, "Credit Risk Agent")) {
            violations.add("The Credit Risk Agent did not approve the RFQ.");
        }
        if (!agentPassed(result, "Inventory Agent")) {
            violations.add("The Inventory Agent did not approve the RFQ.");
        }
        if (!findAgentDetails(result, "Credit Risk Agent").path("evidence_retrieved").asBoolean(false)) {
            violations.add("Client credit evidence was not retrieved.");
        }

        BigDecimal notional = decimal(extracted.path("notional").asText(null), "extracted notional", violations);
        BigDecimal quoteNotional = decimal(quote.path("notional").asText(null), "quote notional", violations);
        String issuer = extracted.path("issuer").asText("");
        String quoteIssuer = quote.path("issuer").asText("");
        int maturityYear = extracted.path("maturity_year").asInt(0);
        String side = extracted.path("side").asText("");

        if (notional != null && quoteNotional != null && notional.compareTo(quoteNotional) != 0) {
            violations.add("Quote notional differs from the extracted RFQ.");
        }
        if (issuer.isBlank() || !issuer.equalsIgnoreCase(quoteIssuer)) {
            violations.add("Quote issuer differs from the extracted RFQ.");
        }
        if (maturityYear < 1900 || maturityYear > 2200 || quote.path("maturity_year").asInt() != maturityYear) {
            violations.add("Quote maturity differs from the extracted RFQ.");
        }
        if (!("BUY".equals(side) || "SELL".equals(side)) || !side.equals(quote.path("side").asText())) {
            violations.add("Quote side differs from the extracted RFQ.");
        }
        if (notional == null || notional.signum() <= 0 || notional.compareTo(ABSOLUTE_NOTIONAL_CEILING) > 0) {
            violations.add("Notional exceeds the absolute finance-gate ceiling or is invalid.");
        }

        CreditRow credit = loadCreditRow(rfq.getClientId(), violations);
        InventoryRow inventory = loadInventory(issuer, maturityYear, violations);
        if (credit != null && notional != null) {
            BigDecimal activeReservations = jdbcTemplate.queryForObject(
                    "SELECT COALESCE(SUM(amount), 0) FROM credit_reservations WHERE client_id = ? AND rfq_id <> ? AND expires_at > now()",
                    BigDecimal.class,
                    rfq.getClientId(), rfq.getId());
            BigDecimal remaining = credit.limit().subtract(credit.exposure()).subtract(activeReservations);
            if (notional.compareTo(remaining) > 0) {
                violations.add("Credit limit exceeded after including outstanding quote reservations.");
            }
        }
        if (inventory != null && notional != null) {
            BigDecimal activeInventoryReservations = jdbcTemplate.queryForObject(
                    """
                    SELECT COALESCE(SUM(amount), 0)
                    FROM bond_inventory_reservations
                    WHERE isin = ? AND rfq_id <> ? AND expires_at > now()
                    """,
                    BigDecimal.class,
                    inventory.isin(), rfq.getId());
            BigDecimal remainingInventoryCapacity = inventory.available()
                    .add(inventory.hedgeCapacity())
                    .subtract(activeInventoryReservations);
            if (notional.compareTo(remainingInventoryCapacity) > 0) {
                violations.add("Requested notional exceeds inventory and hedge capacity after active reservations.");
            }
            if (Duration.between(inventory.updatedAt(), Instant.now()).compareTo(MAX_MARKET_AGE) > 0) {
                violations.add("Market or inventory snapshot is stale.");
            }
            validatePrice(quote, side, notional, inventory.marketMidYield(), violations);
        }

        boolean approved = violations.isEmpty();
        if (approved) {
            Instant expiresAt = Instant.now().plusSeconds(QUOTE_RESERVATION_SECONDS);
            jdbcTemplate.update(
                    """
                    INSERT INTO credit_reservations (rfq_id, client_id, amount, expires_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (rfq_id) DO UPDATE SET amount = EXCLUDED.amount, expires_at = EXCLUDED.expires_at
                    """,
                    rfq.getId(), rfq.getClientId(), notional, Timestamp.from(expiresAt));
            jdbcTemplate.update(
                    """
                    INSERT INTO bond_inventory_reservations (rfq_id, isin, amount, expires_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (rfq_id) DO UPDATE
                    SET isin = EXCLUDED.isin, amount = EXCLUDED.amount, expires_at = EXCLUDED.expires_at
                    """,
                    rfq.getId(), inventory.isin(), notional, Timestamp.from(expiresAt));
        } else {
            jdbcTemplate.update("DELETE FROM credit_reservations WHERE rfq_id = ?", rfq.getId());
            jdbcTemplate.update("DELETE FROM bond_inventory_reservations WHERE rfq_id = ?", rfq.getId());
            logger.warn("Finance gate rejected RFQ {}: {}", rfq.getId(), String.join("; ", violations));
        }
        return finish(result, rfq, approved ? RfqStatus.QUOTED : RfqStatus.REJECTED, violations, approved, notional);
    }

    private CreditRow loadCreditRow(String clientId, List<String> violations) {
        List<CreditRow> rows = jdbcTemplate.query(
                "SELECT credit_limit, current_exposure FROM client_credit_limits WHERE client_id = ? FOR UPDATE",
                (rs, rowNum) -> new CreditRow(rs.getBigDecimal("credit_limit"), rs.getBigDecimal("current_exposure")),
                clientId);
        if (rows.isEmpty()) {
            violations.add("No authoritative client credit profile exists.");
            return null;
        }
        return rows.getFirst();
    }

    private InventoryRow loadInventory(String issuer, int maturityYear, List<String> violations) {
        List<InventoryRow> rows = jdbcTemplate.query(
                """
                SELECT isin, available_notional, hedge_capacity, market_mid_yield, updated_at
                FROM bond_inventory
                WHERE issuer ILIKE ? AND maturity_year = ?
                ORDER BY updated_at DESC LIMIT 1
                FOR UPDATE
                """,
                (rs, rowNum) -> new InventoryRow(
                        rs.getString("isin"),
                        rs.getBigDecimal("available_notional"),
                        rs.getBigDecimal("hedge_capacity"),
                        rs.getBigDecimal("market_mid_yield"),
                        rs.getTimestamp("updated_at").toInstant()),
                "%" + issuer + "%",
                maturityYear);
        if (rows.isEmpty()) {
            violations.add("No authoritative inventory and market snapshot exists.");
            return null;
        }
        return rows.getFirst();
    }

    private void validatePrice(JsonNode quote, String side, BigDecimal notional, BigDecimal midYield, List<String> violations) {
        BigDecimal baseSpreadBps = new BigDecimal("8").add(
                notional.compareTo(new BigDecimal("50000000")) >= 0 ? new BigDecimal("3") : BigDecimal.ZERO);
        BigDecimal adjustmentBps = decimal(quote.path("spread_adjustment_bps").asText(null), "spread adjustment", violations);
        BigDecimal spreadBps = decimal(quote.path("spread_bps").asText(null), "spread", violations);
        if (adjustmentBps == null || adjustmentBps.signum() < 0 || adjustmentBps.compareTo(new BigDecimal("5")) > 0) {
            violations.add("Pricing agent spread adjustment is outside the allowed 0-5 bp range.");
        } else if (spreadBps == null || spreadBps.compareTo(baseSpreadBps.add(adjustmentBps)) != 0) {
            violations.add("Quoted spread does not equal the deterministic base plus the approved bounded adjustment.");
        }
        if (spreadBps == null) {
            return;
        }
        BigDecimal signedSpread = spreadBps.divide(new BigDecimal("100"));
        BigDecimal expectedYield = "BUY".equals(side) ? midYield.add(signedSpread) : midYield.subtract(signedSpread);
        BigDecimal expectedPrice = new BigDecimal("100").subtract(expectedYield.subtract(midYield).multiply(new BigDecimal("5")));
        if (!matches(quote.path("quote_yield_pct").asText(null), expectedYield.setScale(3, RoundingMode.HALF_UP))) {
            violations.add("Quoted yield does not match the exact-decimal yield calculation.");
        }
        if (!matches(quote.path("clean_price").asText(null), expectedPrice.setScale(3, RoundingMode.HALF_UP))) {
            violations.add("Quoted clean price does not match the exact-decimal price calculation.");
        }
    }

    private GateResult finish(
            ObjectNode result,
            RfqRecord rfq,
            RfqStatus status,
            List<String> violations,
            boolean approved,
            BigDecimal reservedNotional) {
        ObjectNode gate = result.putObject("finance_gate");
        gate.put("authority", "Spring Boot deterministic gate");
        gate.put("approved", approved);
        gate.put("absolute_notional_ceiling", ABSOLUTE_NOTIONAL_CEILING.toPlainString());
        gate.put("reservation_seconds", approved ? QUOTE_RESERVATION_SECONDS : 0);
        gate.put("client_id", rfq.getClientId());
        if (reservedNotional != null && approved) {
            gate.put("reserved_notional", reservedNotional.toPlainString());
        }
        ArrayNode reasons = gate.putArray("violations");
        violations.forEach(reasons::add);
        if (status != RfqStatus.QUOTED) {
            result.putNull("quote");
        }
        result.put("status", status.name());
        ArrayNode steps = result.withArray("steps");
        ObjectNode step = steps.addObject();
        step.put("agent", "Finance Gate");
        step.put("status", approved ? "APPROVED" : "REJECTED");
        step.put("summary", approved ? "Java deterministic rules approved and reserved quote capacity." : "Java deterministic rules blocked quote output.");
        step.set("details", gate.deepCopy());
        return new GateResult(status, result);
    }

    private JsonNode findAgentDetails(JsonNode result, String name) {
        for (JsonNode step : result.path("steps")) {
            if (name.equals(step.path("agent").asText())) {
                return step.path("details");
            }
        }
        return JsonNodeFactory.instance.objectNode();
    }

    private boolean agentPassed(JsonNode result, String name) {
        for (JsonNode step : result.path("steps")) {
            if (name.equals(step.path("agent").asText())) {
                return "PASS".equals(step.path("status").asText());
            }
        }
        return false;
    }

    private BigDecimal decimal(String value, String field, List<String> violations) {
        try {
            return value == null ? null : new BigDecimal(value);
        } catch (NumberFormatException exception) {
            violations.add("Invalid " + field + ".");
            return null;
        }
    }

    private boolean matches(String value, BigDecimal expected) {
        try {
            return value != null && new BigDecimal(value).compareTo(expected) == 0;
        } catch (NumberFormatException exception) {
            return false;
        }
    }

    private String text(JsonNode node, String field) {
        return node.path(field).asText("");
    }

    private record CreditRow(BigDecimal limit, BigDecimal exposure) {}
    private record InventoryRow(
            String isin,
            BigDecimal available,
            BigDecimal hedgeCapacity,
            BigDecimal marketMidYield,
            Instant updatedAt) {}
    public record GateResult(RfqStatus status, JsonNode result) {}
}