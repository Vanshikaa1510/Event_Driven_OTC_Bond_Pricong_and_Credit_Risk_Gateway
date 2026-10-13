package com.otc.rfq.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "rfq_audit_events")
public class RfqAuditEvent {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "rfq_id", nullable = false)
    private UUID rfqId;

    @Column(name = "event_type", nullable = false, length = 64)
    private String eventType;

    @Column(name = "previous_status", length = 32)
    private String previousStatus;

    @Column(name = "new_status", nullable = false, length = 32)
    private String newStatus;

    @Column(name = "occurred_at", nullable = false)
    private Instant occurredAt;

    protected RfqAuditEvent() {}

    public RfqAuditEvent(UUID rfqId, String eventType, String previousStatus, String newStatus, Instant occurredAt) {
        this.rfqId = rfqId;
        this.eventType = eventType;
        this.previousStatus = previousStatus;
        this.newStatus = newStatus;
        this.occurredAt = occurredAt;
    }

    public Long getId() { return id; }
    public UUID getRfqId() { return rfqId; }
    public String getEventType() { return eventType; }
    public String getPreviousStatus() { return previousStatus; }
    public String getNewStatus() { return newStatus; }
    public Instant getOccurredAt() { return occurredAt; }
}
