package com.otc.rfq.service;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.otc.rfq.domain.RfqRecord;
import com.otc.rfq.domain.RfqStatus;
import com.otc.rfq.repository.OutboxRepository;
import com.otc.rfq.repository.RfqAuditRepository;
import com.otc.rfq.repository.RfqRepository;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class RfqServiceTest {
    private final RfqRepository rfqRepository = mock(RfqRepository.class);
    private final OutboxRepository outboxRepository = mock(OutboxRepository.class);
    private final RfqAuditRepository rfqAuditRepository = mock(RfqAuditRepository.class);
    private final FinanceGateService financeGateService = mock(FinanceGateService.class);
    private final RfqService rfqService =
            new RfqService(rfqRepository, outboxRepository, rfqAuditRepository, new ObjectMapper(), financeGateService);

    @Test
    void delayedProcessingEventDoesNotDowngradeTerminalResult() {
        RfqRecord rfq = rfq(RfqStatus.QUOTED);
        when(rfqRepository.findById(rfq.getId())).thenReturn(Optional.of(rfq));

        rfqService.applyStatus(rfq.getId(), RfqStatus.PROCESSING);

        org.junit.jupiter.api.Assertions.assertEquals(RfqStatus.QUOTED, rfq.getStatus());
        verify(rfqRepository, never()).save(rfq);
    }

    @Test
    void duplicateResultDoesNotReevaluateOrChangeTerminalResult() {
        RfqRecord rfq = rfq(RfqStatus.QUOTED);
        when(rfqRepository.findById(rfq.getId())).thenReturn(Optional.of(rfq));

        rfqService.applyResult(rfq.getId(), new ObjectMapper().createObjectNode());

        org.junit.jupiter.api.Assertions.assertEquals(RfqStatus.QUOTED, rfq.getStatus());
        verify(financeGateService, never()).evaluateAndReserve(rfq, new ObjectMapper().createObjectNode());
        verify(rfqRepository, never()).save(rfq);
        verify(rfqAuditRepository, never()).save(org.mockito.ArgumentMatchers.any());
    }

    @Test
    void processingTransitionIsAuditedOnce() {
        RfqRecord rfq = new RfqRecord(
                UUID.randomUUID(), "DEMO-001", "test-key", "sample RFQ", Instant.now());
        when(rfqRepository.findById(rfq.getId())).thenReturn(Optional.of(rfq));

        rfqService.applyStatus(rfq.getId(), RfqStatus.PROCESSING);
        rfqService.applyStatus(rfq.getId(), RfqStatus.PROCESSING);

        org.junit.jupiter.api.Assertions.assertEquals(RfqStatus.PROCESSING, rfq.getStatus());
        org.mockito.ArgumentCaptor<com.otc.rfq.domain.RfqAuditEvent> audit =
                org.mockito.ArgumentCaptor.forClass(com.otc.rfq.domain.RfqAuditEvent.class);
        verify(rfqAuditRepository).save(audit.capture());
        org.junit.jupiter.api.Assertions.assertEquals("STATUS_CHANGED", audit.getValue().getEventType());
        org.junit.jupiter.api.Assertions.assertEquals("RECEIVED", audit.getValue().getPreviousStatus());
        org.junit.jupiter.api.Assertions.assertEquals("PROCESSING", audit.getValue().getNewStatus());
    }

    private RfqRecord rfq(RfqStatus status) {
        RfqRecord rfq = new RfqRecord(
                UUID.randomUUID(), "DEMO-001", "test-key", "sample RFQ", Instant.now());
        rfq.applyResult(status, "{\"status\":\"QUOTED\"}");
        return rfq;
    }
}
