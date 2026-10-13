package com.otc.rfq.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "rfqs", uniqueConstraints = @UniqueConstraint(name = "uk_rfq_client_idempotency", columnNames = {"client_id", "idempotency_key"}))
public class RfqRecord {
    @Id
    private UUID id;

    @Column(name = "client_id", nullable = false, length = 64)
    private String clientId;

    @Column(name = "idempotency_key", nullable = false, length = 128)
    private String idempotencyKey;

    @Column(name = "raw_text", nullable = false, columnDefinition = "text")
    private String rawText;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 32)
    private RfqStatus status;

    @Column(name = "result_json", columnDefinition = "jsonb")
    private String resultJson;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected RfqRecord() {}

    public RfqRecord(UUID id, String clientId, String idempotencyKey, String rawText, Instant now) {
        this.id = id;
        this.clientId = clientId;
        this.idempotencyKey = idempotencyKey;
        this.rawText = rawText;
        this.status = RfqStatus.RECEIVED;
        this.createdAt = now;
        this.updatedAt = now;
    }

    public UUID getId() { return id; }
    public String getClientId() { return clientId; }
    public String getRawText() { return rawText; }
    public RfqStatus getStatus() { return status; }
    public String getResultJson() { return resultJson; }
    public Instant getCreatedAt() { return createdAt; }

    public void markProcessing() {
        if (isTerminal()) {
            return;
        }
        this.status = RfqStatus.PROCESSING;
        this.updatedAt = Instant.now();
    }

    public void applyResult(RfqStatus newStatus, String resultJson) {
        if (isTerminal()) {
            return;
        }
        this.status = newStatus;
        this.resultJson = resultJson;
        this.updatedAt = Instant.now();
    }

    public boolean isTerminal() {
        return status == RfqStatus.QUOTED
                || status == RfqStatus.REJECTED
                || status == RfqStatus.NEEDS_REVIEW
                || status == RfqStatus.FAILED;
    }
}