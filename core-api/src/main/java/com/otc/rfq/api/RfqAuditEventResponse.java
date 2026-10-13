package com.otc.rfq.api;

import com.otc.rfq.domain.RfqAuditEvent;
import java.time.Instant;
import java.util.UUID;

public record RfqAuditEventResponse(
        Long id,
        UUID rfqId,
        String eventType,
        String previousStatus,
        String newStatus,
        Instant occurredAt) {
    public static RfqAuditEventResponse from(RfqAuditEvent event) {
        return new RfqAuditEventResponse(
                event.getId(),
                event.getRfqId(),
                event.getEventType(),
                event.getPreviousStatus(),
                event.getNewStatus(),
                event.getOccurredAt());
    }
}
