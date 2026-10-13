package com.otc.rfq.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.otc.rfq.api.ApiExceptionHandler.RfqNotFoundException;
import com.otc.rfq.api.CreateRfqRequest;
import com.otc.rfq.api.RfqAuditEventResponse;
import com.otc.rfq.api.RfqResponse;
import com.otc.rfq.domain.OutboxEvent;
import com.otc.rfq.domain.RfqAuditEvent;
import com.otc.rfq.domain.RfqRecord;
import com.otc.rfq.domain.RfqStatus;
import com.otc.rfq.repository.OutboxRepository;
import com.otc.rfq.repository.RfqAuditRepository;
import com.otc.rfq.repository.RfqRepository;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class RfqService {
    private final RfqRepository rfqRepository;
    private final OutboxRepository outboxRepository;
    private final RfqAuditRepository rfqAuditRepository;
    private final ObjectMapper objectMapper;
    private final FinanceGateService financeGateService;

    public RfqService(
            RfqRepository rfqRepository,
            OutboxRepository outboxRepository,
            RfqAuditRepository rfqAuditRepository,
            ObjectMapper objectMapper,
            FinanceGateService financeGateService) {
        this.rfqRepository = rfqRepository;
        this.outboxRepository = outboxRepository;
        this.rfqAuditRepository = rfqAuditRepository;
        this.objectMapper = objectMapper;
        this.financeGateService = financeGateService;
    }

    @Transactional
    public RfqResponse submit(CreateRfqRequest request, String suppliedKey) {
        String idempotencyKey = suppliedKey == null || suppliedKey.isBlank() ? UUID.randomUUID().toString() : suppliedKey;
        var existing = rfqRepository.findByClientIdAndIdempotencyKey(request.clientId(), idempotencyKey);
        if (existing.isPresent()) {
            return response(existing.get());
        }

        Instant now = Instant.now();
        UUID rfqId = UUID.randomUUID();
        RfqRecord record = rfqRepository.saveAndFlush(
                new RfqRecord(rfqId, request.clientId(), idempotencyKey, request.rawText(), now));
        rfqAuditRepository.save(new RfqAuditEvent(rfqId, "SUBMITTED", null, RfqStatus.RECEIVED.name(), now));
        String payload = writeJson(Map.of(
                "schema_version", 1,
                "event_id", UUID.randomUUID(),
                "rfq_id", rfqId,
                "client_id", request.clientId(),
                "raw_text", request.rawText(),
                "created_at", now));
        outboxRepository.save(new OutboxEvent(UUID.randomUUID(), rfqId, "rfq.received", payload));
        return response(record);
    }

    @Transactional(readOnly = true)
    public RfqResponse get(UUID id) {
        return response(rfqRepository.findById(id).orElseThrow(() -> new RfqNotFoundException(id)));
    }

    @Transactional(readOnly = true)
    public List<RfqResponse> list(int limit) {
        return rfqRepository.findAllByOrderByCreatedAtDesc(PageRequest.of(0, limit)).stream()
                .map(this::response)
                .toList();
    }

    @Transactional(readOnly = true)
    public List<RfqAuditEventResponse> getAuditHistory(UUID rfqId) {
        if (!rfqRepository.existsById(rfqId)) {
            throw new RfqNotFoundException(rfqId);
        }
        return rfqAuditRepository.findAllByRfqIdOrderByOccurredAtAscIdAsc(rfqId).stream()
                .map(RfqAuditEventResponse::from)
                .toList();
    }

    @Transactional
    public void applyStatus(UUID rfqId, RfqStatus status) {
        RfqRecord record = rfqRepository.findById(rfqId).orElseThrow(() -> new RfqNotFoundException(rfqId));
        if (record.isTerminal()) {
            return;
        }
        RfqStatus previousStatus = record.getStatus();
        if (status == RfqStatus.PROCESSING) {
            if (previousStatus == RfqStatus.PROCESSING) {
                return;
            }
            record.markProcessing();
        } else {
            record.applyResult(status, record.getResultJson());
        }
        rfqRepository.save(record);
        appendStatusAudit(rfqId, "STATUS_CHANGED", previousStatus, record.getStatus());
    }

    @Transactional
    public void applyResult(UUID rfqId, JsonNode result) {
        RfqRecord record = rfqRepository.findById(rfqId).orElseThrow(() -> new RfqNotFoundException(rfqId));
        if (record.isTerminal()) {
            return;
        }
        FinanceGateService.GateResult gated = financeGateService.evaluateAndReserve(record, result);
        RfqStatus previousStatus = record.getStatus();
        record.applyResult(gated.status(), gated.result().toString());
        rfqRepository.save(record);
        appendStatusAudit(rfqId, "FINANCE_GATE_DECISION", previousStatus, record.getStatus());
    }

    private void appendStatusAudit(UUID rfqId, String eventType, RfqStatus previousStatus, RfqStatus newStatus) {
        if (previousStatus != newStatus) {
            rfqAuditRepository.save(new RfqAuditEvent(
                    rfqId, eventType, previousStatus.name(), newStatus.name(), Instant.now()));
        }
    }

    private RfqResponse response(RfqRecord record) {
        JsonNode result = null;
        if (record.getResultJson() != null) {
            try {
                result = objectMapper.readTree(record.getResultJson());
            } catch (JsonProcessingException exception) {
                throw new IllegalStateException("Stored RFQ result is invalid JSON", exception);
            }
        }
        return RfqResponse.from(record, result);
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not serialize RFQ event", exception);
        }
    }
}