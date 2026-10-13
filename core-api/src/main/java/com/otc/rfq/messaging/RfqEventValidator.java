package com.otc.rfq.messaging;

import com.fasterxml.jackson.databind.JsonNode;
import com.otc.rfq.domain.RfqStatus;
import java.time.Instant;
import java.util.UUID;
import org.springframework.stereotype.Component;

@Component
public class RfqEventValidator {
    private static final int SUPPORTED_SCHEMA_VERSION = 1;
    private static final int MAX_RFQ_TEXT_LENGTH = 20_000;

    public UUID validateStatus(JsonNode event) {
        validateVersion(event);
        UUID rfqId = requiredUuid(event, "rfq_id");
        String status = requiredString(event, "status", 32);
        RfqStatus parsedStatus;
        try {
            parsedStatus = RfqStatus.valueOf(status);
        } catch (IllegalArgumentException exception) {
            throw new IllegalArgumentException("Unsupported RFQ status", exception);
        }
        if (parsedStatus != RfqStatus.PROCESSING && parsedStatus != RfqStatus.FAILED) {
            throw new IllegalArgumentException("Status events may only set PROCESSING or FAILED");
        }
        return rfqId;
    }

    public UUID validateProcessed(JsonNode event) {
        validateVersion(event);
        UUID rfqId = requiredUuid(event, "rfq_id");
        requiredString(event, "client_id", 64);
        requiredInstant(event, "processed_at");
        JsonNode result = event.get("result");
        if (result == null || !result.isObject() || result.isEmpty()) {
            throw new IllegalArgumentException("Event field 'result' must be a non-empty object");
        }
        String resultStatus = requiredString(result, "status", 64);
        if (!resultStatus.equals("QUOTE_PROPOSED")
                && !resultStatus.equals("REJECTED")
                && !resultStatus.equals("NEEDS_REVIEW")) {
            throw new IllegalArgumentException("Event result has an unsupported status");
        }
        return rfqId;
    }

    private void validateVersion(JsonNode event) {
        if (event == null || !event.isObject()) {
            throw new IllegalArgumentException("Kafka event must be a JSON object");
        }
        JsonNode version = event.get("schema_version");
        if (version == null || !version.isIntegralNumber() || !version.canConvertToInt()
                || version.intValue() != SUPPORTED_SCHEMA_VERSION) {
            throw new IllegalArgumentException("Unsupported or missing Kafka event schema_version");
        }
    }

    private UUID requiredUuid(JsonNode event, String field) {
        try {
            return UUID.fromString(requiredString(event, field, 36));
        } catch (IllegalArgumentException exception) {
            throw new IllegalArgumentException("Event field '" + field + "' must be a UUID", exception);
        }
    }

    private String requiredString(JsonNode event, String field, int maxLength) {
        JsonNode value = event.get(field);
        if (value == null || !value.isTextual() || value.asText().isBlank() || value.asText().length() > maxLength) {
            throw new IllegalArgumentException("Event field '" + field + "' is missing or invalid");
        }
        return value.asText();
    }

    private Instant requiredInstant(JsonNode event, String field) {
        try {
            return Instant.parse(requiredString(event, field, 64));
        } catch (RuntimeException exception) {
            throw new IllegalArgumentException("Event field '" + field + "' must be an ISO-8601 timestamp", exception);
        }
    }
}
