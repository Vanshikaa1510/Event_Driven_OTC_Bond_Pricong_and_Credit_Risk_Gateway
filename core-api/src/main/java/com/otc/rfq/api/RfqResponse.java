package com.otc.rfq.api;

import com.fasterxml.jackson.databind.JsonNode;
import com.otc.rfq.domain.RfqRecord;
import com.otc.rfq.domain.RfqStatus;
import java.time.Instant;
import java.util.UUID;

public record RfqResponse(
        UUID id,
        String clientId,
        String rawText,
        RfqStatus status,
        JsonNode result,
        Instant createdAt) {
    public static RfqResponse from(RfqRecord rfq, JsonNode result) {
        return new RfqResponse(rfq.getId(), rfq.getClientId(), rfq.getRawText(), rfq.getStatus(), result, rfq.getCreatedAt());
    }
}