package com.otc.rfq.messaging;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.otc.rfq.domain.RfqStatus;
import com.otc.rfq.service.RfqService;
import java.util.UUID;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.junit.jupiter.api.Test;

class RfqEventValidatorTest {
    private static final UUID RFQ_ID = UUID.fromString("461fa8b3-0c8f-4f1e-86bf-e043047a2eab");
    private final ObjectMapper objectMapper = new ObjectMapper();
    private final RfqEventValidator validator = new RfqEventValidator();

    @Test
    void acceptsVersionOneStatusEvent() throws Exception {
        var event = objectMapper.readTree("""
                {"schema_version":1,"rfq_id":"461fa8b3-0c8f-4f1e-86bf-e043047a2eab","status":"PROCESSING"}
                """);

        assertEquals(RFQ_ID, validator.validateStatus(event));
    }

    @Test
    void rejectsUnknownStatusSchemaVersion() throws Exception {
        var event = objectMapper.readTree("""
                {"schema_version":2,"rfq_id":"461fa8b3-0c8f-4f1e-86bf-e043047a2eab","status":"PROCESSING"}
                """);

        assertThrows(IllegalArgumentException.class, () -> validator.validateStatus(event));
    }

    @Test
    void acceptsVersionOneProcessedEventFromWorker() throws Exception {
        var event = objectMapper.readTree("""
                {
                  "schema_version":1,
                  "rfq_id":"461fa8b3-0c8f-4f1e-86bf-e043047a2eab",
                  "client_id":"DEMO-001",
                  "processed_at":"2026-10-10T06:00:00Z",
                  "result":{"status":"QUOTE_PROPOSED","steps":[],"quote":null}
                }
                """);

        assertEquals(RFQ_ID, validator.validateProcessed(event));
    }

    @Test
    void rejectsInvalidStatusEventBeforeCallingService() throws Exception {
        RfqService rfqService = mock(RfqService.class);
        RfqEventListener listener = new RfqEventListener(objectMapper, rfqService, validator);
        ConsumerRecord<String, String> record = new ConsumerRecord<>(
                "rfq.status",
                0,
                0,
                "key",
                "{\"schema_version\":1,\"rfq_id\":\"461fa8b3-0c8f-4f1e-86bf-e043047a2eab\",\"status\":\"QUOTED\"}");

        assertThrows(IllegalArgumentException.class, () -> listener.onStatus(record));
        verify(rfqService, never()).applyStatus(RFQ_ID, RfqStatus.QUOTED);
    }

    @Test
    void rejectsProcessedEventMissingDecisionStatus() throws Exception {
        var event = objectMapper.readTree("""
                {
                  "schema_version":1,
                  "rfq_id":"461fa8b3-0c8f-4f1e-86bf-e043047a2eab",
                  "client_id":"DEMO-001",
                  "processed_at":"2026-10-10T06:00:00Z",
                  "result":{"steps":[]}
                }
                """);

        assertThrows(IllegalArgumentException.class, () -> validator.validateProcessed(event));
    }
}
